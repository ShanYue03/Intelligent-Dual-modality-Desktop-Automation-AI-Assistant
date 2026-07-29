"""
LLM layer: Groq chat API — main Llama 3.1 8B Instant.

FALLBACK: Llama 3.3 70B — used only when the main model errors or returns empty.

Adapted from D:/Documents/FYP/LLM/benchmark_llm.py (requests + OpenAI-compatible API).
Other providers in benchmark_llm are omitted here but can be re-enabled similarly.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_a, **_k):
        return False

LAYER_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = LAYER_ROOT.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
RESULT_DIR = LAYER_ROOT / "results"
RESULT_CSV = RESULT_DIR / "llm_layer_results.csv"

from user_store import DEFAULT_USER, get_current_user_name  # noqa: E402

load_dotenv(LAYER_ROOT / ".env")

RESULT_DIR.mkdir(parents=True, exist_ok=True)

MAIN_MODEL = "llama-3.1-8b-instant"
# FALLBACK — Groq Llama 3.3 70B (re-enable in `run_llm` loop when implementing production fallbacks)
FALLBACK_MODEL = "llama-3.3-70b-versatile"

# From benchmark_llm — commented alternative stacks (kept for reference)
# BENCHMARK_MODELS = [
#     {"label": "Groq Llama 3.3 70B", "fn": "groq", "model": "llama-3.3-70b-versatile"},
#     {"label": "Groq Llama 3.1 8B Instant", "fn": "groq", "model": "llama-3.1-8b-instant"},
#     ...
# ]

CSV_HEADER = [
    "timestamp_utc",
    "model_id",
    "user_prompt",
    "response",
    "latency_s",
    "status",
    "router_uncertain",
]


def _post(url, **kwargs):
    return requests.post(url, timeout=120, **kwargs)


def _message_text_from_chat_response(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    raw = msg.get("content")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts = []
        for p in raw:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text") or "")
            elif isinstance(p, dict) and "text" in p:
                parts.append(p.get("text") or "")
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts).strip()
    return str(raw).strip()


def call_groq(model: str, prompt: str) -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise ValueError("Missing GROQ_API_KEY (set in LLM/.env)")
    r = _post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 512,
        },
    )
    r.raise_for_status()
    return _message_text_from_chat_response(r.json())


def _response_failed(answer: str) -> bool:
    if not answer or not answer.strip():
        return True
    return answer.strip().upper().startswith("ERROR")


def _append_row(row: List[str]) -> None:
    new_file = (not RESULT_CSV.is_file()) or RESULT_CSV.stat().st_size == 0
    with RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if new_file:
            w.writerow(CSV_HEADER)
        w.writerow(row)


def build_voice_assistant_prompt(
    user_english_text: str,
    voice_language: str,
    router_uncertain: bool,
) -> str:
    lines = []
    if voice_language == "zh":
        lines.append(
            "You are a voice assistant. Reply in Simplified Chinese, concise (about 1–3 short sentences)."
        )
    else:
        lines.append(
            "You are a voice assistant. Reply in English, concise (about 1–3 short sentences)."
        )
    if router_uncertain:
        lines.append(
            "The intent classifier was uncertain whether this is a system command. "
            "Interpret what the user wants, answer helpfully, and briefly confirm your understanding."
        )
    current_user = get_current_user_name() or DEFAULT_USER
    lines.append(
        f"The current user's name is {current_user}. Use this name in greetings only when it feels natural or necessary."
    )
    lines.append(f"User said (transcribed in English): {user_english_text}")
    return "\n".join(lines)


def run_llm(
    user_english_text: str,
    voice_language: str,
    router_uncertain: bool,
) -> Tuple[str, str, float]:
    """
    Returns (response_text, model_used, latency_s_for_successful_call_only).
    """
    prompt = build_voice_assistant_prompt(
        user_english_text, voice_language, router_uncertain
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    models_to_try = (MAIN_MODEL, FALLBACK_MODEL)

    last_error = ""
    for model_id in models_to_try:
        t0 = time.perf_counter()
        try:
            answer = call_groq(model_id, prompt)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            answer = f"ERROR: HTTP {code} from API"
        except requests.RequestException as e:
            answer = f"ERROR: network ({type(e).__name__})"
        except Exception as e:
            answer = f"ERROR: {e}"
        latency_s = time.perf_counter() - t0

        status = "ok" if not _response_failed(answer) else "error"
        _append_row(
            [
                ts,
                model_id,
                prompt[:2000],
                answer[:8000],
                f"{latency_s:.4f}",
                status,
                str(router_uncertain),
            ]
        )

        if not _response_failed(answer):
            return answer.strip(), model_id, latency_s

        last_error = answer

    return (last_error or "ERROR: all models failed"), models_to_try[-1], latency_s


if __name__ == "__main__":
    print("=== LLM layer (Groq) ===")
    t = input("User text (English): ").strip()
    vl = input("Voice lang zh/en [en]: ").strip() or "en"
    u = input("Router uncertain y/n [n]: ").strip().lower() == "y"
    text, mid, lat = run_llm(t, vl, u)
    print("Model:", mid, "Latency:", lat)
    print(text)
    print("CSV:", RESULT_CSV)
