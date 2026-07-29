"""
TTS layer: language-specific mains — Chinese: Edge TTS; English: Piper.
Fallbacks (Piper for zh, Edge for en) are wired in comments for later enablement.

Adapted from D:/Documents/FYP/TTS/benchmark_tts.py
- gTTS and other engines are commented out (not removed).
"""

from __future__ import annotations

import csv
import ctypes
import os
import shutil
import subprocess
import time
import urllib.request
import winsound
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# from gtts import gTTS  # optional benchmark engine (disabled)

LAYER_ROOT = Path(__file__).resolve().parent
MODEL_DIR = LAYER_ROOT / "models" / "piper"
AUDIO_DIR = LAYER_ROOT / "audio"
RESULT_DIR = LAYER_ROOT / "results"
RESULT_CSV = RESULT_DIR / "tts_layer_results.csv"

for folder in (MODEL_DIR, AUDIO_DIR, RESULT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

LANGUAGE_CONFIG = {
    "en": {
        "name": "English",
        "edge_voice": "en-US-AriaNeural",
        "piper_voice_path": MODEL_DIR / "en_US-hfc_female-medium.onnx",
        "piper_config_path": MODEL_DIR / "en_US-hfc_female-medium.onnx.json",
        "piper_model_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/"
            "hfc_female/medium/en_US-hfc_female-medium.onnx"
        ),
        "piper_config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/"
            "hfc_female/medium/en_US-hfc_female-medium.onnx.json"
        ),
    },
    "zh": {
        "name": "Chinese",
        "edge_voice": "zh-CN-XiaoxiaoNeural",
        "piper_voice_path": MODEL_DIR / "zh_CN-huayan-medium.onnx",
        "piper_config_path": MODEL_DIR / "zh_CN-huayan-medium.onnx.json",
        "piper_model_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/"
            "huayan/medium/zh_CN-huayan-medium.onnx"
        ),
        "piper_config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/"
            "huayan/medium/zh_CN-huayan-medium.onnx.json"
        ),
    },
}

CSV_HEADER = [
    "timestamp_utc",
    "language",
    "engine",
    "text_preview",
    "latency_s",
    "output_path",
    "status",
    "note",
]


def play_wav_file(wav_path: Path) -> None:
    winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)


def _mci_send(command: str) -> None:
    """Send MCI command via winmm; raise a readable error on failure."""
    err = ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
    if err != 0:
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(err, buf, len(buf))
        msg = buf.value or f"MCI error code {err}"
        raise RuntimeError(msg)


def play_mp3_file(mp3_path: Path) -> None:
    """Play MP3 directly (no external player window) using Windows MCI."""
    alias = f"va_tts_{int(time.time() * 1000)}"
    quoted = str(mp3_path).replace('"', "")
    _mci_send(f'open "{quoted}" type mpegvideo alias {alias}')
    try:
        _mci_send(f"play {alias} wait")
    finally:
        try:
            _mci_send(f"close {alias}")
        except Exception:
            pass


def play_audio_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        play_wav_file(path)
        return
    if suffix == ".mp3":
        play_mp3_file(path)
        return
    raise ValueError(f"Unsupported audio format for direct playback: {suffix}")


def safe_download(url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        return
    print(f"Downloading: {target_path.name}")
    urllib.request.urlretrieve(url, str(target_path))


def _append_csv(row: List[str]) -> None:
    new_file = (not RESULT_CSV.is_file()) or RESULT_CSV.stat().st_size == 0
    with RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(CSV_HEADER)
        w.writerow(row)


def run_piper_tts(text: str, language: str) -> Dict[str, object]:
    info = LANGUAGE_CONFIG[language]
    output_wav = AUDIO_DIR / f"out_piper_{language}.wav"
    gen_start: Optional[float] = None
    try:
        safe_download(info["piper_model_url"], Path(info["piper_voice_path"]))
        safe_download(info["piper_config_url"], Path(info["piper_config_path"]))

        piper_exe = shutil.which("piper")
        if not piper_exe:
            raise FileNotFoundError(
                "piper executable not on PATH. Install piper (e.g. pip install piper-tts) "
                "or add Piper to PATH."
            )

        command = [
            piper_exe,
            "--model",
            str(info["piper_voice_path"]),
            "--config",
            str(info["piper_config_path"]),
            "--output_file",
            str(output_wav),
        ]
        gen_start = time.perf_counter()
        subprocess.run(
            command,
            input=text,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        duration = time.perf_counter() - gen_start
        play_wav_file(output_wav)
        return {
            "engine": "piper",
            "status": "ok",
            "latency_s": duration,
            "output_path": str(output_wav),
            "note": "",
        }
    except Exception as ex:
        duration = (time.perf_counter() - gen_start) if gen_start is not None else 0.0
        return {
            "engine": "piper",
            "status": "error",
            "latency_s": duration,
            "output_path": str(output_wav),
            "note": str(ex),
        }


def run_edge_tts(text: str, language: str) -> Dict[str, object]:
    info = LANGUAGE_CONFIG[language]
    output_mp3 = AUDIO_DIR / f"out_edge_{language}.mp3"
    gen_start: Optional[float] = None
    try:
        edge_tts_cmd = shutil.which("edge-tts")
        if not edge_tts_cmd:
            raise FileNotFoundError(
                "edge-tts not on PATH. Install: python -m pip install edge-tts"
            )
        command = [
            edge_tts_cmd,
            "--voice",
            info["edge_voice"],
            "--text",
            text,
            "--write-media",
            str(output_mp3),
        ]
        gen_start = time.perf_counter()
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.perf_counter() - gen_start
        play_audio_file(output_mp3)
        return {
            "engine": "edge-tts",
            "status": "ok",
            "latency_s": duration,
            "output_path": str(output_mp3),
            "note": "played directly",
        }
    except subprocess.CalledProcessError as ex:
        duration = (time.perf_counter() - gen_start) if gen_start is not None else 0.0
        err_tail = (ex.stderr or "").strip()
        if len(err_tail) > 800:
            err_tail = err_tail[:800] + "..."
        note = str(ex) if not err_tail else f"{ex}\nstderr: {err_tail}"
        return {
            "engine": "edge-tts",
            "status": "error",
            "latency_s": duration,
            "output_path": str(output_mp3),
            "note": note,
        }
    except Exception as ex:
        duration = (time.perf_counter() - gen_start) if gen_start is not None else 0.0
        return {
            "engine": "edge-tts",
            "status": "error",
            "latency_s": duration,
            "output_path": str(output_mp3),
            "note": str(ex),
        }


# def run_gtts(text: str, language: str) -> Dict[str, object]:
#     """gTTS benchmark path — disabled in integrated assistant."""
#     ...


def speak(text: str, voice_language: str) -> Dict[str, object]:
    """
    Synthesize and play audio.
    Chinese: Edge TTS main; Piper fallback if Edge fails.
    English: Piper main; Edge fallback if Piper fails.
    voice_language: 'en' | 'zh'
    Returns last attempt dict with keys engine, status, latency_s, output_path, note.
    """
    if voice_language not in LANGUAGE_CONFIG:
        raise ValueError("voice_language must be 'en' or 'zh'")
    if not (text or "").strip():
        raise ValueError("TTS text is empty")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    preview = text.strip().replace("\n", " ")[:200]

    if voice_language == "zh":
        runners = (run_edge_tts, run_piper_tts)
    else:
        runners = (run_piper_tts, run_edge_tts)

    for runner in runners:
        out = runner(text, voice_language)
        _append_csv(
            [
                ts,
                voice_language,
                out["engine"],
                preview,
                f"{out['latency_s']:.4f}",
                str(out["output_path"]),
                out["status"],
                (out.get("note") or "")[:500],
            ]
        )
        if out["status"] == "ok":
            return out

    return out


if __name__ == "__main__":
    print("=== TTS layer ===")
    c = input("1=Chinese 2=English [2]: ").strip()
    lang = "zh" if c == "1" else "en"
    txt = input("Text: ").strip() or "Hello from the voice assistant."
    print(speak(txt, lang))
    print("CSV:", RESULT_CSV)
