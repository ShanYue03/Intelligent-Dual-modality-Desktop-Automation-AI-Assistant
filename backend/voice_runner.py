"""One voice round using existing Voice_Architecture layers (unchanged logic)."""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VOICE_ROOT = PROJECT_ROOT / "Voice_Architecture"
if str(VOICE_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICE_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(VOICE_ROOT / "LLM" / ".env")
except ImportError:
    pass

from ASR.asr_layer import log_asr_result, transcribe_to_english  # noqa: E402
from Router.router_layer import route_text_uncertain_flag  # noqa: E402
from LLM.llm_layer import run_llm  # noqa: E402
from TTS.tts_layer import speak  # noqa: E402
from System.session_ops import (  # noqa: E402
    is_session_no_match_reply,
    pop_idle_timeout_message,
    session_active,
    session_no_match_speech,
    touch_session_activity,
)
from System.system_layer import (  # noqa: E402
    pending_system_confirmation,
    run_system,
    system_command_hint,
)

_INTENT_LABELS = {
    "session_youtube": "Open YouTube",
    "session_wikipedia": "Open Wikipedia",
    "session_google_maps": "Open Google Maps",
    "session_google_news": "Open Google News",
    "open_url": "Open URL",
    "open_app": "Open application",
    "web_search": "Web search",
    "screenshot": "Take screenshot",
    "timer": "Set timer",
    "volume": "Adjust volume",
    "time": "Current time",
    "date": "Today's date",
}


def automation_session_active() -> bool:
    """True when a browser/WhatsApp automation session or yes/no confirm is in progress."""
    return session_active() or pending_system_confirmation()


def matches_open_gesture_control(voice_lang: str, english: str, original: str) -> bool:
    """Voice hotkey: open/launch gesture control (en + zh)."""
    if voice_lang == "zh":
        text = (original or english or "").strip()
        if not text:
            return False
        if not re.search(r"(打开|开启)", text):
            return False
        return bool(re.search(r"(手势控制|手动控制)", text))
    text = (english or original or "").lower()
    if not re.search(r"\b(open|launch)\b", text):
        return False
    return bool(re.search(r"gesture\s*control", text))


def should_continue_automation_loop(round_result: dict[str, Any]) -> bool:
    """
    Match Voice_Architecture/main.py: keep recording while automation or confirm is active.
    Stop only on session_stop / session_none or when the session has ended.
    """
    intent = str(round_result.get("intent") or "")
    if intent in ("session_stop", "session_none", "switch_gesture"):
        return False
    if intent.startswith("session_"):
        return True
    if round_result.get("automation_active"):
        return True
    if round_result.get("error") == "empty_transcript" and automation_session_active():
        return True
    return automation_session_active()


def intent_to_command_label(
    intent: str,
    transcript_original: str,
    transcript_english: str = "",
) -> str:
    """Audit log detail: prefer what the user actually said."""
    text = (transcript_original or transcript_english or "").strip()
    if text:
        return text[:120]

    label = _INTENT_LABELS.get(intent or "")
    if label:
        return label

    return "Voice command"


def transcribe_session_audio(voice_lang: str, audio_path: Path) -> dict[str, Any]:
    """ASR only — used to push transcript to the UI before routing/LLM/TTS."""
    if voice_lang not in ("zh", "en"):
        raise ValueError("voice_lang must be 'zh' or 'en'")

    try:
        english, original, sr_latency, asr_extra, model_used = transcribe_to_english(
            audio_path, voice_lang
        )
    except Exception as exc:
        log_asr_result(
            voice_lang, "", "", audio_path, 0.0, error_note=f"error: {exc}"
        )
        raise

    log_asr_result(
        voice_lang,
        original,
        english,
        audio_path,
        sr_latency,
        asr_extra=asr_extra or "",
        model=model_used,
    )
    system_hint = system_command_hint(voice_lang, english, original)
    return {
        "transcript_original": original,
        "transcript_english": english,
        "system_command_hint": system_hint,
        "zh_system_hint": system_hint,
        "asr_latency_s": sr_latency,
        "asr_extra": asr_extra,
        "empty": not english and not system_hint,
    }


def process_voice_transcript(
    voice_lang: str,
    english: str,
    original: str,
    system_command_hint_text: str,
    *,
    on_status: Optional[Callable[[str, str], None]] = None,
    response_time_start: float | None = None,
) -> dict[str, Any]:
    """Router → LLM/system → TTS after transcript is known."""
    if voice_lang not in ("zh", "en"):
        raise ValueError("voice_lang must be 'zh' or 'en'")

    start = response_time_start if response_time_start is not None else time.perf_counter()

    def elapsed_response_time_ms() -> float:
        return (time.perf_counter() - start) * 1000.0

    def status(msg: str, *, reply: str = "") -> None:
        if on_status:
            on_status(msg, reply)

    if matches_open_gesture_control(voice_lang, english, original):
        reply = "正在打开手势控制" if voice_lang == "zh" else "Opening gesture control"
        response_time_ms = elapsed_response_time_ms()
        status("speaking", reply=reply)
        speak(reply, voice_lang)
        first_command = (original or english or "Open gesture control").strip()[:120]
        return {
            "ok": True,
            "transcript_original": original,
            "transcript_english": english,
            "reply": reply,
            "first_command": first_command,
            "intent": "switch_gesture",
            "automation_active": False,
            "asr_latency_s": 0.0,
            "asr_extra": {},
            "response_time_ms": response_time_ms,
        }

    idle_notice = pop_idle_timeout_message()
    if idle_notice:
        speak(idle_notice, voice_lang)

    touch_session_activity()
    status("routing")

    if pending_system_confirmation() or session_active():
        route_info = {
            "predicted_label": "system",
            "confidence": 1.0,
            "route_system": True,
            "needs_llm_reconfirm": False,
            "latency_s": 0.0,
            "model": "n/a_session_or_confirm",
        }
        router_uncertain = False
    else:
        if system_command_hint_text:
            route_info = {
                "predicted_label": "system",
                "confidence": 1.0,
                "route_system": True,
                "needs_llm_reconfirm": False,
                "latency_s": 0.0,
                "model": "keyword_map",
            }
            router_uncertain = False
        else:
            route_info, router_uncertain = route_text_uncertain_flag(english)

    first_command = ""
    reply = ""
    speech_reply = ""
    intent = "none"

    if route_info["route_system"]:
        status("system")
        system_text = system_command_hint_text if system_command_hint_text else english
        sys_out = run_system(voice_lang, system_text, source_text=original)
        reply = str(sys_out["reply"])
        speech_reply = (
            session_no_match_speech(voice_lang)
            if is_session_no_match_reply(reply)
            else reply
        )
        intent = str(sys_out.get("intent", "system"))
        first_command = intent_to_command_label(intent, original, english)
    else:
        status("llm")
        reply, _model, _lat = run_llm(english, voice_lang, router_uncertain)
        speech_reply = reply
        intent = "llm"
        first_command = intent_to_command_label(intent, original, english)

    response_time_ms = elapsed_response_time_ms()
    status("speaking", reply=reply)
    speak(speech_reply, voice_lang)

    return {
        "ok": True,
        "transcript_original": original,
        "transcript_english": english,
        "reply": reply,
        "first_command": first_command,
        "intent": intent,
        "automation_active": automation_session_active(),
        "asr_latency_s": 0.0,
        "asr_extra": {},
        "response_time_ms": response_time_ms,
    }


def run_voice_round(
    voice_lang: str,
    audio_path: Path,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Transcribe then run router → LLM/system → TTS (single call for CLI)."""
    response_time_start = time.perf_counter()
    if on_status:
        on_status("transcribing", "")
    t = transcribe_session_audio(voice_lang, audio_path)
    if t["empty"]:
        return {
            "ok": False,
            "transcript_original": t["transcript_original"],
            "transcript_english": t["transcript_english"],
            "reply": "",
            "first_command": "",
            "intent": "none",
            "error": "empty_transcript",
            "asr_latency_s": t["asr_latency_s"],
            "asr_extra": t["asr_extra"],
        }
    out = process_voice_transcript(
        voice_lang,
        t["transcript_english"],
        t["transcript_original"],
        t.get("system_command_hint") or t.get("zh_system_hint", ""),
        on_status=on_status,
        response_time_start=response_time_start,
    )
    out["asr_latency_s"] = t["asr_latency_s"]
    out["asr_extra"] = t["asr_extra"]
    return out
