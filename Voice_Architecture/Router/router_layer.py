"""
Router layer: zero-shot NLI -> system vs LLM (chat).

Adapted from D:/Documents/FYP/Router/NLI_routerBenchmark.py
- Model: MoritzLaurer/deberta-v3-large-zeroshot-v1.1-all-33
- Route to system only if top label is 'system' AND confidence > threshold.
"""

from __future__ import annotations

import csv
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
from transformers import pipeline
from transformers.utils import logging as hf_logging

hf_logging.set_verbosity_error()

LAYER_ROOT = Path(__file__).resolve().parent
RESULT_DIR = LAYER_ROOT / "results"
RESULT_CSV = RESULT_DIR / "router_layer_results.csv"

# Reuse the same HF hub cache as a normal install (~/.cache/huggingface), where weights
# usually already live. A project-local .cache forced a second download and cold tree.
# Override anytime with HF_HOME in the environment.
os.environ.setdefault(
    "HF_HOME",
    str(Path.home() / ".cache" / "huggingface"),
)

RESULT_DIR.mkdir(parents=True, exist_ok=True)

NLI_MODELS = [
    # "facebook/bart-large-mnli",
    # "roberta-large-mnli",
    "MoritzLaurer/deberta-v3-large-zeroshot-v1.1-all-33",
    # "cross-encoder/nli-deberta-v3-base",
]

CANDIDATES = ["system", "chat"]
CONFIDENCE_THRESHOLD = 0.6

# If utterance contains "open" plus a known site/app name, skip NLI and route to system layer.
_OPEN_SITE_PATTERNS = [
    r"\byoutube\b",
    r"\bchatgpt\b|\bchat\s*gpt\b",
    r"\bgoogle\s+maps\b",
    r"\bwikipedia\b",
    r"\bgoogle\s+news\b|\bgooglenews\b",
    r"\bwhatsapp\b|\bwhat'?s?\s*app\b",
]


def _matches_open_site_keyword(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if not re.search(r"\bopen\b", t):
        return False
    return any(re.search(p, t) for p in _OPEN_SITE_PATTERNS)


# Route arithmetic to LLM 
_MATH_OP_SYMBOL = re.compile(
    r"\d+\s*[\+\-\*\/×÷]\s*\d+"
    r"|[\+\-\*\/×÷]\s*\d+"
    r"|\d+\s*[\+\-\*\/×÷]"
)
_MATH_WORDS_EN = re.compile(
    r"\b(add|plus|minus|subtract|multiplied|multiply|times|divided|divide)\b",
    re.I,
)
_MATH_WORDS_ZH = re.compile(r"(加|加上|减|减去|乘|乘以|除|除以)")
_ZH_NUMERALS = re.compile(r"[零一二三四五六七八九十百千万两俩]")
_EN_NUMBER_WORDS = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b",
    re.I,
)


def _has_math_operand(text: str) -> bool:
    return bool(
        re.search(r"\d", text)
        or _ZH_NUMERALS.search(text)
        or _EN_NUMBER_WORDS.search(text)
    )


# Route explain queries to LLM
_EXPLAIN_EN = re.compile(r"explain", re.I)


def _matches_explain_query(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _EXPLAIN_EN.search(t):
        return True
    return "解释" in t


def _matches_math_calculation_query(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _MATH_OP_SYMBOL.search(t):
        return True
    if _MATH_WORDS_ZH.search(t) and _has_math_operand(t):
        return True
    if _MATH_WORDS_EN.search(t) and _has_math_operand(t):
        return True
    return False


CSV_HEADER = [
    "timestamp_utc",
    "input_text",
    "predicted_label",
    "confidence",
    "route_system",
    "needs_llm_reconfirm",
    "latency_s",
    "model",
]

_pipeline = None
_pipeline_model_name: Optional[str] = None


def _get_classifier(model_name: str):
    global _pipeline, _pipeline_model_name
    if _pipeline is not None and _pipeline_model_name == model_name:
        return _pipeline
    device = 0 if torch.cuda.is_available() else -1
    _pipeline = pipeline(
        "zero-shot-classification",
        model=model_name,
        device=device,
    )
    _pipeline_model_name = model_name
    return _pipeline


def _append_result_row(row: List[str]) -> None:
    new_file = (not RESULT_CSV.is_file()) or RESULT_CSV.stat().st_size == 0
    with RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(CSV_HEADER)
        w.writerow(row)


def route_text(text: str) -> Dict[str, object]:
    """
    Classify text; return routing decision and metrics.
    route_system: True only if predicted 'system' with confidence > CONFIDENCE_THRESHOLD.
    needs_llm_reconfirm: True when we send to LLM due to low confidence on system or chat intent.

    Keyword override: ``open`` + (youtube | chatgpt | google maps | wikipedia | google news) →
    always ``route_system`` (skips DeBERTa).

    Keyword override: arithmetic (+ - * / or add/minus/multiply/divide, en + zh) →
    always ``route_system`` False (LLM). Router input is the English slot from ASR (translated
    zh→en, or Chinese fallback when translation fails).

    Keyword override: ``explain`` (en) or ``解释`` (zh) → always ``route_system`` False (LLM).
    """
    if not (text or "").strip():
        raise ValueError("Router input text is empty")

    if _matches_explain_query(text):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _append_result_row(
            [
                ts,
                text,
                "chat",
                "1.000000",
                "False",
                "False",
                "0.0000",
                "keyword_explain",
            ]
        )
        return {
            "predicted_label": "chat",
            "confidence": 1.0,
            "route_system": False,
            "needs_llm_reconfirm": False,
            "latency_s": 0.0,
            "model": "keyword_explain",
        }

    if _matches_math_calculation_query(text):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _append_result_row(
            [
                ts,
                text,
                "chat",
                "1.000000",
                "False",
                "False",
                "0.0000",
                "keyword_math",
            ]
        )
        return {
            "predicted_label": "chat",
            "confidence": 1.0,
            "route_system": False,
            "needs_llm_reconfirm": False,
            "latency_s": 0.0,
            "model": "keyword_math",
        }

    if _matches_open_site_keyword(text):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _append_result_row(
            [
                ts,
                text,
                "system",
                "1.000000",
                "True",
                "False",
                "0.0000",
                "keyword_open_site",
            ]
        )
        return {
            "predicted_label": "system",
            "confidence": 1.0,
            "route_system": True,
            "needs_llm_reconfirm": False,
            "latency_s": 0.0,
            "model": "keyword_open_site",
        }

    model_name = NLI_MODELS[0]
    clf = _get_classifier(model_name)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    t0 = time.perf_counter()
    res = clf(text, candidate_labels=CANDIDATES, multi_label=False)
    latency_s = time.perf_counter() - t0

    pred_label = res["labels"][0].lower()
    confidence = float(res["scores"][0])

    route_system = pred_label == "system" and confidence > CONFIDENCE_THRESHOLD
    # Weak "system" prediction: send to LLM with reconfirmation wording
    needs_llm_reconfirm = pred_label == "system" and confidence <= CONFIDENCE_THRESHOLD

    _append_result_row(
        [
            ts,
            text,
            pred_label,
            f"{confidence:.6f}",
            str(route_system),
            str(needs_llm_reconfirm),
            f"{latency_s:.4f}",
            model_name,
        ]
    )

    return {
        "predicted_label": pred_label,
        "confidence": confidence,
        "route_system": route_system,
        "needs_llm_reconfirm": needs_llm_reconfirm,
        "latency_s": latency_s,
        "model": model_name,
    }


def route_text_uncertain_flag(text: str) -> Tuple[Dict[str, object], bool]:
    """
    Returns (route_dict, llm_uncertain_prompt_flag).
    llm_uncertain_prompt_flag True -> LLM should confirm interpretation (weak system route).
    """
    r = route_text(text)
    uncertain = bool(r.get("needs_llm_reconfirm"))
    return r, uncertain


if __name__ == "__main__":
    print("=== Router layer ===")
    q = input("Enter query text: ").strip()
    if not q:
        raise SystemExit("Empty query")
    out = route_text(q)
    print(out)
