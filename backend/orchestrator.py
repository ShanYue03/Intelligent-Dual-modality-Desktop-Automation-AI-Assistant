"""Single-process coordinator: mutex for voice/gesture, WebSocket broadcast."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from controller_audit import (  # noqa: E402
    DEFAULT_CSV,
    append_session_audit,
    format_activity_display,
    is_gesture_audit_row,
    is_voice_audit_row,
    parse_cpu_utilization,
    parse_memory_usage,
    parse_response_time_ms,
    read_audit_rows,
)
from .system_metrics import (  # noqa: E402
    CpuSnapshot,
    capture_session_metrics,
    get_cpu_snapshot,
)
from .voice_chat_history import sanitize_chat_text  # noqa: E402

GESTURE_ROOT = PROJECT_ROOT / "Gesture_Architecture"
if str(GESTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(GESTURE_ROOT))

# Delay before system chat bubble so it aligns closer with audible TTS playback.
SYSTEM_CHAT_DISPLAY_DELAY_S = 1.0


@dataclass
class OrchestratorState:
    voice_busy: bool = False
    gesture_busy: bool = False
    voice_recording: bool = False
    last_gesture_label: str = ""
    first_gesture_command: str = ""
    dominant_hand: str = "right"
    pending_module_switch: Optional[str] = None
    _gesture_switch_requested: bool = False
    _gesture_stop: threading.Event = field(default_factory=threading.Event)
    _gesture_thread: Optional[threading.Thread] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)


class Orchestrator:
    def __init__(self) -> None:
        self.state = OrchestratorState()
        self._ws_clients: set[Any] = set()
        self._ws_preview_clients: set[Any] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._preview_lock = threading.Lock()
        self._preview_pending: Optional[bytes] = None
        self._preview_flush_scheduled = False
        self._gesture_recognition_times_ms: list[float] = []
        self._gesture_cpu_start: Optional[CpuSnapshot] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register_ws(self, ws: Any, *, preview: bool = False) -> None:
        self._ws_clients.add(ws)
        if preview:
            self._ws_preview_clients.add(ws)

    def unregister_ws(self, ws: Any) -> None:
        self._ws_clients.discard(ws)
        self._ws_preview_clients.discard(ws)

    async def broadcast(self, event: str, payload: dict[str, Any]) -> None:
        if not self._ws_clients:
            return
        message = json.dumps({"event": event, "data": payload})
        dead: list[Any] = []
        for ws in list(self._ws_clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    async def broadcast_preview_frame(self, jpeg_bytes: bytes) -> None:
        """Send raw JPEG (0x01 prefix) to preview subscribers only."""
        if not self._ws_preview_clients or not jpeg_bytes:
            return
        packet = b"\x01" + jpeg_bytes
        dead: list[Any] = []
        for ws in list(self._ws_preview_clients):
            try:
                await ws.send_bytes(packet)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)
            self._ws_preview_clients.discard(ws)

    def _emit_sync(self, event: str, payload: dict[str, Any]) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event, payload), self._loop)

    def _emit_voice_chat(self, role: str, text: str) -> None:
        cleaned = sanitize_chat_text(text)
        if not cleaned:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._emit_sync(
            "voice.chat",
            {"role": role, "text": cleaned, "timestamp": ts},
        )

    def _schedule_system_chat(self, text: str) -> None:
        """Show system bubble shortly after TTS starts (not before audio is heard)."""
        cleaned = sanitize_chat_text(text)
        if not cleaned:
            return

        def emit_after_delay() -> None:
            time.sleep(SYSTEM_CHAT_DISPLAY_DELAY_S)
            self._emit_voice_chat("system", cleaned)

        threading.Thread(target=emit_after_delay, daemon=True).start()

    def _emit_preview_sync(self, jpeg_bytes: bytes) -> None:
        """Coalesce preview frames so the event loop is not flooded from the gesture thread."""
        loop = self._loop
        if not loop or not loop.is_running():
            return
        with self._preview_lock:
            self._preview_pending = jpeg_bytes
            if self._preview_flush_scheduled:
                return
            self._preview_flush_scheduled = True
        loop.call_soon_threadsafe(self._flush_preview_pending)

    def _flush_preview_pending(self) -> None:
        with self._preview_lock:
            payload = self._preview_pending
            self._preview_pending = None
            self._preview_flush_scheduled = False
        if payload and self._loop and self._loop.is_running():
            asyncio.create_task(self.broadcast_preview_frame(payload))

    def get_status(self) -> dict[str, Any]:
        return {
            "voice_active": self.state.voice_busy or self.state.voice_recording,
            "gesture_active": self.state.gesture_busy,
            "voice_recording": self.state.voice_recording,
            "last_gesture": self.state.last_gesture_label,
            "dominant_hand": self.state.dominant_hand,
        }

    def set_dominant_hand(self, hand: str) -> dict[str, Any]:
        normalized = hand.strip().lower()
        if normalized not in {"left", "right"}:
            return {"ok": False, "error": "invalid_dominant_hand"}
        with self.state._lock:
            self.state.dominant_hand = normalized
        from gesture_control.runtime import GestureController

        GestureController.set_dominant_hand(normalized)
        self._emit_sync("gesture.dominant_hand", {"hand": normalized})
        return {"ok": True, "dominant_hand": normalized}

    def _busy_other(self, mode: str) -> Optional[str]:
        if mode == "voice" and self.state.gesture_busy:
            return "gesture"
        if mode == "gesture" and (self.state.voice_busy or self.state.voice_recording):
            return "voice"
        return None

    def get_dashboard_data(self) -> dict[str, Any]:
        rows = read_audit_rows(DEFAULT_CSV)
        voice_count = 0
        gesture_count = 0
        successful = 0
        voice_ok = 0
        voice_total = 0
        gesture_ok = 0
        gesture_total = 0
        response_times_ms: list[float] = []
        cpu_values: list[float] = []
        memory_values: list[float] = []

        for row in rows:
            action = row.get("action") or ""
            status = (row.get("status") or "").lower()
            if status == "ok":
                successful += 1
            if is_voice_audit_row(action):
                voice_count += 1
                voice_total += 1
                if status == "ok":
                    voice_ok += 1
            elif is_gesture_audit_row(action):
                gesture_count += 1
                gesture_total += 1
                if status == "ok":
                    gesture_ok += 1

            rt = parse_response_time_ms(row)
            if rt is not None:
                response_times_ms.append(rt)
            cpu = parse_cpu_utilization(row)
            if cpu is not None:
                cpu_values.append(cpu)
            mem = parse_memory_usage(row)
            if mem is not None:
                memory_values.append(mem)

        voice_health = 100.0 if voice_total == 0 else (voice_ok / voice_total) * 100.0
        gesture_health = 100.0 if gesture_total == 0 else (gesture_ok / gesture_total) * 100.0

        avg_cpu = round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else 0.0
        avg_memory = round(sum(memory_values) / len(memory_values), 1) if memory_values else 0.0

        recent = []
        recent_rows = read_audit_rows(DEFAULT_CSV, limit=20)
        for row in reversed(recent_rows):
            action = row.get("action", "")
            ts = row.get("timestamp", "")
            mode, display = format_activity_display(action)
            recent.append(
                {
                    "time": ts,
                    "action": display,
                    "type": mode,
                    "status": row.get("status", ""),
                }
            )

        avg_response_ms = (
            round(sum(response_times_ms) / len(response_times_ms))
            if response_times_ms
            else None
        )

        return {
            "voice_commands": voice_count,
            "gestures_detected": gesture_count,
            "successful_actions": successful,
            "response_time_ms": avg_response_ms,
            "recent_activity": recent,
            "system_status": {
                "voice_recognition_percent": round(voice_health, 1),
                "gesture_detection_percent": round(gesture_health, 1),
                "cpu_utilization_percent": avg_cpu,
                "memory_usage_percent": avg_memory,
            },
        }

    @staticmethod
    def _session_resource_metrics(cpu_start: CpuSnapshot) -> tuple[float, float]:
        cpu_percent, memory_percent = capture_session_metrics(cpu_start)
        return round(cpu_percent, 4), round(memory_percent, 4)

    def _append_voice_audit(
        self,
        first_command: str,
        status: str,
        *,
        cpu_start: CpuSnapshot,
        response_time_ms: float | None = None,
    ) -> None:
        cpu_pct, mem_pct = self._session_resource_metrics(cpu_start)
        append_session_audit(
            "voice",
            first_command,
            status,
            response_time_ms=response_time_ms,
            cpu_utilization=cpu_pct,
            memory_usage=mem_pct,
        )

    async def _run_one_voice_round(
        self,
        voice_lang: str,
        audio_path: Path,
        duration: int,
    ) -> dict[str, Any]:
        from .recording import record_with_levels
        from .voice_runner import process_voice_transcript, transcribe_session_audio

        speech_threshold = 0.08
        round_cpu_start = get_cpu_snapshot()

        def on_level(level: float) -> None:
            self._emit_sync(
                "voice.level",
                {"level": level, "speaking": level >= speech_threshold},
            )

        def on_ready() -> None:
            self._emit_sync("voice.status", {"phase": "recording"})

        self._emit_sync("voice.status", {"phase": "preparing"})

        with self.state._lock:
            self.state.voice_recording = True

        try:
            await asyncio.to_thread(
                record_with_levels,
                audio_path,
                duration,
                on_level=on_level,
                on_ready=on_ready,
            )
        except Exception as exc:
            self._emit_sync("voice.error", {"message": str(exc)})
            return {"ok": False, "error": str(exc)}
        finally:
            with self.state._lock:
                self.state.voice_recording = False

        response_time_start = time.perf_counter()
        self._emit_sync("voice.status", {"phase": "transcribing"})
        t = await asyncio.to_thread(
            transcribe_session_audio,
            voice_lang,
            audio_path,
        )
        original = t.get("transcript_original") or ""
        english = t.get("transcript_english") or ""
        self._emit_sync(
            "voice.transcript",
            {"original": original, "english": english},
        )
        user_line = (original or english).strip()
        if user_line:
            self._emit_voice_chat("user", user_line)

        if t.get("empty"):
            from .voice_runner import automation_session_active

            return {
                "ok": False,
                "transcript_original": original,
                "transcript_english": english,
                "error": "empty_transcript",
                "automation_active": automation_session_active(),
            }

        self._emit_sync("voice.status", {"phase": "processing"})

        def on_status(step: str, reply: str = "") -> None:
            phase = "speaking" if step == "speaking" else "processing"
            self._emit_sync("voice.status", {"phase": phase})
            if step == "speaking" and reply.strip():
                self._schedule_system_chat(reply)

        result = await asyncio.to_thread(
            process_voice_transcript,
            voice_lang,
            english,
            original,
            t.get("system_command_hint") or t.get("zh_system_hint", ""),
            on_status=on_status,
            response_time_start=response_time_start,
        )

        if result.get("ok"):
            first_cmd = (
                (result.get("first_command") or "").strip()
                or (result.get("transcript_original") or "").strip()
                or (result.get("transcript_english") or "").strip()
                or "Voice command"
            )
            response_ms = result.get("response_time_ms")
            self._append_voice_audit(
                first_cmd,
                "ok",
                cpu_start=round_cpu_start,
                response_time_ms=float(response_ms) if response_ms is not None else None,
            )
            return {"ok": True, "transcript_original": original, **result}

        self._append_voice_audit(
            "No speech detected",
            "error",
            cpu_start=round_cpu_start,
        )
        return result

    async def run_voice_session(
        self,
        language: str,
        duration: int = 5,
    ) -> dict[str, Any]:
        voice_lang = "zh" if language in ("CN", "cn", "zh", "chinese") else "en"
        audio_path = PROJECT_ROOT / "Voice_Architecture" / "ASR" / "audio" / "session_input.wav"

        with self.state._lock:
            if self.state.voice_busy or self.state.voice_recording:
                self._emit_sync("voice.status", {"phase": "idle"})
                return {"ok": False, "error": "voice_already_running"}
            other = self._busy_other("voice")
            if other:
                self._emit_sync("voice.status", {"phase": "idle"})
                return {"ok": False, "error": f"{other}_is_active"}
            self.state.voice_busy = True

        from .voice_runner import should_continue_automation_loop

        last_result: dict[str, Any] = {"ok": True}
        automation_loop = False
        pending_switch: Optional[str] = None
        try:
            voice_session_cpu_start = get_cpu_snapshot()
            while True:
                try:
                    last_result = await self._run_one_voice_round(
                        voice_lang,
                        audio_path,
                        duration,
                    )
                except Exception as exc:
                    self._append_voice_audit("Error", "error", cpu_start=voice_session_cpu_start)
                    self._emit_sync("voice.error", {"message": str(exc)})
                    last_result = {"ok": False, "error": str(exc)}
                    break

                keep_listening = should_continue_automation_loop(last_result)
                if keep_listening:
                    automation_loop = True
                    self._emit_sync("voice.automation", {"active": True})
                    self._emit_sync("voice.status", {"phase": "automation_listening"})
                else:
                    if str(last_result.get("intent") or "") == "switch_gesture":
                        pending_switch = "gesture"
                    break

            reply = str(last_result.get("reply") or "")
            self._emit_sync(
                "voice.complete",
                {
                    "ok": bool(last_result.get("ok")),
                    "reply": reply,
                    "automation_loop": automation_loop,
                },
            )
            return {**last_result, "automation_loop": automation_loop}
        finally:
            self._emit_sync("voice.automation", {"active": False})
            with self.state._lock:
                self.state.voice_busy = False
            self._emit_sync("voice.status", {"phase": "idle"})
            if pending_switch:
                self._emit_sync(
                    "module.switch",
                    {"target": pending_switch, "auto_start": True},
                )

    async def start_gesture(self) -> dict[str, Any]:
        with self.state._lock:
            if self.state.gesture_busy:
                return {"ok": False, "error": "gesture_already_running"}
            other = self._busy_other("gesture")
            if other:
                return {"ok": False, "error": f"{other}_is_active"}
            self.state.gesture_busy = True
            self.state._gesture_stop.clear()
            self.state.last_gesture_label = ""
            self.state.first_gesture_command = ""
            self.state.pending_module_switch = None
            self.state._gesture_switch_requested = False
            self._gesture_recognition_times_ms = []
            self._gesture_cpu_start = get_cpu_snapshot()

        def on_gesture(label: str, recognition_latency_s: float = 0.0) -> None:
            from gesture_control.gesture_audit import GestureAuditLogger

            if label == GestureAuditLogger.MODULE_SWITCH_VOICE_LABEL:
                self._emit_sync("gesture.detected", {"gesture": label})
                if recognition_latency_s >= 0:
                    self._gesture_recognition_times_ms.append(
                        recognition_latency_s * 1000.0
                    )
                if not self.state._gesture_switch_requested:
                    self.state._gesture_switch_requested = True
                    self.state.pending_module_switch = "voice"
                    self.state.first_gesture_command = label
                    self.state._gesture_stop.set()
                return
            self.state.last_gesture_label = label
            if not self.state.first_gesture_command:
                self.state.first_gesture_command = label
            if recognition_latency_s > 0:
                self._gesture_recognition_times_ms.append(recognition_latency_s * 1000.0)
            self._emit_sync("gesture.detected", {"gesture": label})

        def on_frame(jpeg_bytes: bytes) -> None:
            self._emit_preview_sync(jpeg_bytes)

        def run() -> None:
            from gesture_control.runtime import GestureController

            GestureController.set_dominant_hand(self.state.dominant_hand)
            controller = GestureController()
            try:
                controller.start(
                    headless=True,
                    on_gesture_detected=on_gesture,
                    on_frame=on_frame,
                    should_stop=self.state._gesture_stop.is_set,
                )
                status = "ok"
            except Exception as exc:
                status = "error"
                self._emit_sync("gesture.error", {"message": str(exc)})
            finally:
                cmd = self.state.first_gesture_command or "Session ended"
                times = self._gesture_recognition_times_ms
                gesture_response_ms = (
                    sum(times) / len(times) if times else None
                )
                cpu_start = self._gesture_cpu_start or get_cpu_snapshot()
                cpu_pct, mem_pct = Orchestrator._session_resource_metrics(cpu_start)
                append_session_audit(
                    "gesture",
                    cmd,
                    status,
                    response_time_ms=gesture_response_ms,
                    cpu_utilization=cpu_pct,
                    memory_usage=mem_pct,
                )
                self._gesture_cpu_start = None
                pending = self.state.pending_module_switch
                self.state.pending_module_switch = None
                self.state._gesture_switch_requested = False
                with self.state._lock:
                    self.state.gesture_busy = False
                self._emit_sync("gesture.stopped", {"ok": status == "ok"})
                if pending:
                    self._emit_sync(
                        "module.switch",
                        {"target": pending, "auto_start": True},
                    )

        self.state._gesture_thread = threading.Thread(target=run, daemon=True)
        self.state._gesture_thread.start()
        self._emit_sync("gesture.started", {})
        return {"ok": True}

    async def stop_gesture(self) -> dict[str, Any]:
        with self.state._lock:
            if not self.state.gesture_busy:
                return {"ok": False, "error": "gesture_not_running"}
        self.state._gesture_stop.set()
        if self.state._gesture_thread:
            await asyncio.to_thread(self.state._gesture_thread.join, 10.0)
        return {"ok": True}


orchestrator = Orchestrator()
