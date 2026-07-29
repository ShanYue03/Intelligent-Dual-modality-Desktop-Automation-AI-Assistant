"""
ASR layer: microphone -> English text (Google Speech Recognition).

Adapted from D:/Documents/FYP/ASR/asr_benchmark.py
- Main: Google SR (+ googletrans for Chinese -> English).
- Fallback: Whisper base (optional; used only when Google SR errors or is empty).
"""

from __future__ import annotations

import csv
import os
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pyaudio
import speech_recognition as sr
from googletrans import Translator
from httpx import Timeout

# googletrans hits unofficial Google endpoints; default httpx timeouts are tight.
_TRANSLATOR: Optional[Translator] = None
_TRANSLATE_TIMEOUT_S = 60.0
_TRANSLATE_RETRIES = 3
_TRANSLATE_BACKOFF_S = (0.8, 2.0, 4.0)

_WHISPER_MODEL = None

LAYER_ROOT = Path(__file__).resolve().parent
AUDIO_DIR = LAYER_ROOT / "audio"
RESULT_DIR = LAYER_ROOT / "results"
RESULT_CSV = RESULT_DIR / "asr_layer_results.csv"
WHISPER_CACHE_DIR = LAYER_ROOT / "models" / "whisper"

CSV_HEADER = [
    "timestamp_utc",
    "user_language",
    "model",
    "transcript_original",
    "transcript_english",
    "latency_s",
    "audio_path",
    "notes",
]

_LEGACY_HEADER = [
    "timestamp_utc",
    "user_language",
    "model",
    "transcript_english",
    "latency_s",
    "audio_path",
    "notes",
]

for d in (AUDIO_DIR, RESULT_DIR, WHISPER_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _get_translator() -> Translator:
    global _TRANSLATOR
    if _TRANSLATOR is None:
        # googletrans forwards timeout to httpx; a bare float breaks (no .as_dict()).
        _TRANSLATOR = Translator(timeout=Timeout(_TRANSLATE_TIMEOUT_S))
    return _TRANSLATOR


def _zh_to_en_googletrans(zh_text: str) -> Tuple[str, str]:
    """
    Chinese -> English via googletrans. Returns (english_text, note_suffix).
    note_suffix is empty on success, or 'googletrans_fallback' if we reuse zh text.
    """
    text = zh_text.strip()
    if not text:
        return "", ""

    last_err: Optional[BaseException] = None
    for attempt in range(_TRANSLATE_RETRIES):
        try:
            translated = _get_translator().translate(text, src="zh-cn", dest="en").text
            return translated.strip(), ""
        except Exception as e:
            last_err = e
            if attempt + 1 < _TRANSLATE_RETRIES:
                time.sleep(_TRANSLATE_BACKOFF_S[attempt])

    print(
        "[ASR] googletrans failed after retries (network / rate limit / server). "
        f"Last error: {last_err!r}. Using Chinese transcript in the English slot so the pipeline can continue."
    )
    return text, "googletrans_fallback"


def _whisper_available() -> bool:
    try:
        import whisper  # noqa: F401
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


def _google_sr_usable(english: str, original: str, language: str) -> bool:
    if language == "zh":
        return bool((original or "").strip())
    return bool((english or "").strip())


def record_audio(output_file: Path, duration: int = 5) -> None:
    """Record voice input from microphone."""
    print(f"\nRecording {duration} seconds of audio...")
    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=1024,
    )
    frames = []
    for _ in range(0, int(16000 / 1024 * duration)):
        data = stream.read(1024)
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    wf = wave.open(str(output_file), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(16000)
    wf.writeframes(b"".join(frames))
    wf.close()
    print(f"Audio saved to: {output_file}")


def transcribe_google_sr_to_english(
    audio_path: Path, language: str
) -> Tuple[str, str, float, str]:
    """
    Google Speech Recognition; returns (english_text, original_text, latency_seconds, extra_note).
    Chinese audio: recognize zh, then translate to English (retries + long timeout; may fall back to zh).
    """
    recognizer = sr.Recognizer()
    with sr.AudioFile(str(audio_path)) as source:
        audio = recognizer.record(source)

    extra_note = ""
    t0 = time.perf_counter()
    try:
        lang_code = "zh-CN" if language == "zh" else "en-US"
        text = recognizer.recognize_google(audio, language=lang_code)
        if language == "zh":
            original = text.strip()
            english, tnote = _zh_to_en_googletrans(original)
            if tnote:
                extra_note = tnote
        else:
            english = text.strip()
            original = english
    except sr.UnknownValueError:
        english = ""
        original = ""
    except sr.RequestError as e:
        english = ""
        original = ""
        raise RuntimeError(f"Google SR request failed: {e}") from e
    latency = time.perf_counter() - t0
    return english, original, latency, extra_note


def transcribe_whisper_to_english(
    audio_path: Path, language: str
) -> Tuple[str, str, float, str]:
    """
    Whisper fallback (optional deps). Chinese: transcribe zh then googletrans to English.
    """
    import torch
    import whisper

    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _WHISPER_MODEL = whisper.load_model(
            "base", download_root=str(WHISPER_CACHE_DIR)
        ).to(device)

    t0 = time.perf_counter()
    if language == "zh":
        result = _WHISPER_MODEL.transcribe(str(audio_path), language="zh", task="transcribe")
        original = result["text"].strip()
        english, tnote = _zh_to_en_googletrans(original)
        extra_note = "whisper_fallback"
        if tnote:
            extra_note = f"{extra_note};{tnote}"
    else:
        result = _WHISPER_MODEL.transcribe(str(audio_path), language="en", task="transcribe")
        english = result["text"].strip()
        original = english
        extra_note = "whisper_fallback"
    latency = time.perf_counter() - t0
    return english, original, latency, extra_note


def transcribe_to_english(
    audio_path: Path, language: str
) -> Tuple[str, str, float, str, str]:
    """
    Main path: Google SR. Fallback: Whisper when Google errors or returns empty.
    Returns (english, original, latency_s, extra_note, model_used).
    """
    google_error = ""
    english = ""
    original = ""
    extra = ""
    latency = 0.0

    try:
        english, original, latency, extra = transcribe_google_sr_to_english(
            audio_path, language
        )
        if _google_sr_usable(english, original, language):
            return english, original, latency, extra, "Google SR"
        google_error = "empty_transcript"
    except Exception as e:
        google_error = str(e)

    if not _whisper_available():
        if google_error and google_error != "empty_transcript":
            raise RuntimeError(f"Google SR failed: {google_error}") from None
        return english, original, latency, extra or google_error, "Google SR"

    try:
        english, original, latency, extra = transcribe_whisper_to_english(
            audio_path, language
        )
        print("[ASR] Google SR unavailable or empty; using Whisper fallback.")
        if _google_sr_usable(english, original, language):
            return english, original, latency, extra, "Whisper"
        whisper_note = extra or "whisper_empty"
        if google_error:
            whisper_note = f"{whisper_note};google_sr:{google_error}"
        return english, original, latency, whisper_note, "Whisper"
    except Exception as whisper_err:
        if google_error and google_error != "empty_transcript":
            raise RuntimeError(
                f"Google SR failed ({google_error}); "
                f"Whisper fallback also failed ({whisper_err})"
            ) from whisper_err
        note = extra or google_error or f"whisper_failed:{whisper_err}"
        return english, original, latency, note, "Google SR"


def _ensure_asr_csv_schema() -> None:
    """One-time upgrade: insert transcript_original before transcript_english."""
    if not RESULT_CSV.is_file() or RESULT_CSV.stat().st_size == 0:
        return
    with RESULT_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] == CSV_HEADER:
        return
    if rows[0] != _LEGACY_HEADER:
        return

    upgraded: List[List[str]] = [CSV_HEADER]
    for row in rows[1:]:
        if len(row) < 7:
            upgraded.append(row)
            continue
        english = row[3]
        upgraded.append(row[:3] + [english, english] + row[4:])

    with RESULT_CSV.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(upgraded)


def _append_result_row(row: List[str]) -> None:
    _ensure_asr_csv_schema()
    new_file = (not RESULT_CSV.is_file()) or RESULT_CSV.stat().st_size == 0
    with RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(CSV_HEADER)
        w.writerow(row)


def log_asr_result(
    user_language: str,
    original: str,
    english: str,
    audio_path: Path,
    sr_latency: float,
    *,
    asr_extra: str = "",
    error_note: str = "",
    timestamp: str | None = None,
    model: str = "Google SR",
) -> None:
    """Append one ASR row to asr_layer_results.csv (standalone + integrated app)."""
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    original = (original or "").strip()
    english = (english or "").strip()
    if error_note:
        notes = error_note
    else:
        notes = "" if (original or english) else "empty_transcript"
        if asr_extra:
            notes = f"{notes};{asr_extra}" if notes else asr_extra
    _append_result_row(
        [
            ts,
            user_language,
            model,
            original,
            english,
            f"{sr_latency:.4f}",
            str(audio_path),
            notes,
        ]
    )


def run_asr(user_language: str, duration_seconds: int = 5) -> Dict[str, object]:
    """
    Record from mic, run Google SR (Whisper fallback on error), return English text + metrics.
    user_language: 'zh' | 'en'
    """
    if user_language not in ("zh", "en"):
        raise ValueError("user_language must be 'zh' or 'en'")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audio_path = AUDIO_DIR / "session_input.wav"
    record_audio(audio_path, duration_seconds)

    try:
        english, original_text, sr_latency, asr_extra, model_used = transcribe_to_english(
            audio_path, user_language
        )
    except Exception as e:
        log_asr_result(
            user_language,
            "",
            "",
            audio_path,
            0.0,
            error_note=f"error: {e}",
            timestamp=ts,
        )
        raise

    log_asr_result(
        user_language,
        original_text,
        english,
        audio_path,
        sr_latency,
        asr_extra=asr_extra,
        timestamp=ts,
        model=model_used,
    )

    return {
        "transcript_english": english,
        "transcript_original": original_text,
        "latency_s": sr_latency,
        "audio_path": str(audio_path),
        "model": model_used,
    }


if __name__ == "__main__":
    print("=== ASR layer (Google SR + Whisper fallback) ===")
    lang = input("Language 1=Chinese 2=English [1/2]: ").strip()
    ul = "zh" if lang == "1" else "en"
    d = input("Duration seconds (default 5): ").strip()
    dur = int(d) if d else 5
    out = run_asr(ul, dur)
    print("English transcript:", out["transcript_english"])
    print("Model:", out["model"])
    print("Latency (layer):", f"{out['latency_s']:.4f}s")
    print("CSV:", RESULT_CSV)
