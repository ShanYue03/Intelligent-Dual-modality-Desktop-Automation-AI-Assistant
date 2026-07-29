"""Microphone capture with RMS level events for UI (does not modify ASR layer)."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Callable, Optional


def record_with_levels(
    output_file: Path,
    duration: int = 5,
    *,
    on_level: Optional[Callable[[float], None]] = None,
    on_ready: Optional[Callable[[], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    """Record mono 16 kHz WAV; invoke on_level with normalized RMS 0..1 per chunk."""
    try:
        import pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "PyAudio is not installed for this Python. "
            "Activate your conda env (multimodal_assistant) and run: "
            "pip install PyAudio"
        ) from exc

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=1024,
    )
    if on_ready:
        on_ready()
    frames: list[bytes] = []
    chunks = int(16000 / 1024 * duration)
    for i in range(chunks):
        if should_stop and should_stop():
            break
        data = stream.read(1024, exception_on_overflow=False)
        frames.append(data)
        if on_level:
            samples = struct.unpack(f"<{len(data) // 2}h", data)
            if samples:
                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                on_level(min(1.0, rms / 4000.0))
    stream.stop_stream()
    stream.close()
    p.terminate()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    wf = wave.open(str(output_file), "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(b"".join(frames))
    wf.close()
