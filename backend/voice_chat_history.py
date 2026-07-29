"""Merge ASR + TTS CSV logs into chronological chat messages (last N days)."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASR_CSV = PROJECT_ROOT / "Voice_Architecture" / "ASR" / "results" / "asr_layer_results.csv"
TTS_CSV = PROJECT_ROOT / "Voice_Architecture" / "TTS" / "results" / "tts_layer_results.csv"


def sanitize_chat_text(text: str) -> str:
    t = (text or "").strip()
    if "CDP connect failed" in t:
        return "CDP connect failed"
    return t


def _parse_ts(ts: str) -> datetime | None:
    raw = (ts or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def load_voice_chat_history(days: int = 3) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    messages: list[dict[str, Any]] = []

    if ASR_CSV.is_file():
        with ASR_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ts = _parse_ts(row.get("timestamp_utc", ""))
                if ts is None or ts < cutoff:
                    continue
                notes = (row.get("notes") or "").lower()
                if "empty_transcript" in notes:
                    continue
                text = sanitize_chat_text(
                    row.get("transcript_original")
                    or row.get("transcript_english")
                    or ""
                )
                if not text:
                    continue
                messages.append(
                    {
                        "role": "user",
                        "text": text,
                        "timestamp": row.get("timestamp_utc", ""),
                    }
                )

    if TTS_CSV.is_file():
        with TTS_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ts = _parse_ts(row.get("timestamp_utc", ""))
                if ts is None or ts < cutoff:
                    continue
                text = sanitize_chat_text(row.get("text_preview") or "")
                if not text:
                    continue
                messages.append(
                    {
                        "role": "system",
                        "text": text,
                        "timestamp": row.get("timestamp_utc", ""),
                    }
                )

    messages.sort(key=lambda m: m.get("timestamp") or "")
    return messages
