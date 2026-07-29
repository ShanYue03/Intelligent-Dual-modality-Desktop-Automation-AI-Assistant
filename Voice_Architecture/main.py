from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ASR.asr_layer import run_asr  # noqa: E402
from Router.router_layer import route_text_uncertain_flag  # noqa: E402
from LLM.llm_layer import run_llm  # noqa: E402
from TTS.tts_layer import speak  # noqa: E402
from System.session_ops import (  # noqa: E402
    pop_idle_timeout_message,
    session_active,
    touch_session_activity,
)
from System.system_layer import (  # noqa: E402
    pending_system_confirmation,
    run_system,
    system_command_hint,
)


def _pick_language() -> str:
    print("Select voice / UI language:")
    print("  1 = Chinese (中文)")
    print("  2 = English")
    choice = input("Enter choice [1/2] (default 2): ").strip()
    return "zh" if choice == "1" else "en"


def _recording_duration() -> int:
    raw = input("Recording duration in seconds (default 5): ").strip()
    if not raw:
        return 5
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def main() -> None:
    print("=== Intelligent Voice Assistant (FYP) ===\n")
    voice_lang = _pick_language()
    duration = _recording_duration()
    print()

    round_num = 0
    while True:
        round_num += 1
        print(f"[Round {round_num}]")

        idle_notice = pop_idle_timeout_message()
        if idle_notice:
            print("\n[Session] Idle timeout (1 hour with no speech).")
            speak(idle_notice, voice_lang)

        print("[1/4] ASR (Google Speech Recognition)...")
        asr_out = run_asr(voice_lang, duration)
        text_en = (asr_out.get("transcript_english") or "").strip()
        text_original = (asr_out.get("transcript_original") or "").strip()
        system_hint = system_command_hint(voice_lang, text_en, text_original)
        print(f"  English transcript: {text_en or '(empty)'}")
        if voice_lang == "zh":
            print(f"  Original transcript: {text_original or '(empty)'}")
        print(f"  ASR latency (recognition): {asr_out['latency_s']:.4f}s")

        if not text_en and not system_hint:
            if session_active():
                print(
                    "  No speech detected. Session still active — try again, "
                    "or wait; session ends after 1 hour without speech."
                )
                continue
            print("No speech detected. Exiting.")
            return

        touch_session_activity()

        print("\n[2/4] Router (DeBERTa zero-shot)...")
        if pending_system_confirmation() or session_active():
            print(
                "  (Skipping router: pending confirmation or active session mode.)"
            )
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
            print("  Loading / running classifier (first run may download weights)...")
            if system_hint:
                route_info = {
                    "predicted_label": "system",
                    "confidence": 1.0,
                    "route_system": True,
                    "needs_llm_reconfirm": False,
                    "latency_s": 0.0,
                    "model": "keyword_map",
                }
                router_uncertain = False
                print("  (Skipping classifier: system command matched local keyword map.)")
            else:
                route_info, router_uncertain = route_text_uncertain_flag(text_en)
                print(
                    f"  label={route_info['predicted_label']} "
                    f"confidence={route_info['confidence']:.4f} "
                    f"route_system={route_info['route_system']}"
                )
                print(f"  Router latency: {route_info['latency_s']:.4f}s")

        if route_info["route_system"]:
            print("\n[3/4] System layer -> skipping LLM.")
            system_text = system_hint if system_hint else text_en
            sys_out = run_system(voice_lang, system_text, source_text=text_original)
            reply = str(sys_out["reply"])
            print(f"  intent={sys_out.get('intent')} status={sys_out.get('status')}")
            print(f"  Reply text: {reply}")
            print(f"  System layer latency: {sys_out['latency_s']:.4f}s")
        else:
            print("\n[3/4] LLM (Groq: 8B instant, 70B fallback)...")
            reply, model_used, llm_lat = run_llm(text_en, voice_lang, router_uncertain)
            print(f"  Model used: {model_used}")
            print(f"  LLM latency (successful call): {llm_lat:.4f}s")
            print(f"  Reply text: {reply}")

        print("\n[4/4] TTS (Piper, Edge fallback)...")
        tts_out = speak(reply, voice_lang)
        print(
            f"  Engine: {tts_out['engine']} status={tts_out['status']} "
            f"latency={tts_out['latency_s']:.4f}s"
        )
        if tts_out["status"] != "ok":
            print(f"  TTS note: {tts_out.get('note', '')}")

        if session_active() or pending_system_confirmation():
            print(
                "\n--- Continue: same recording length. "
                "Say stop automation or stop operation to end, or session ends after 1 hour with no speech. ---\n"
            )
            continue

        print("\nDone.")
        print(f"  ASR CSV:   {ROOT / 'ASR' / 'results' / 'asr_layer_results.csv'}")
        print(f"  Router CSV:{ROOT / 'Router' / 'results' / 'router_layer_results.csv'}")
        print(f"  LLM CSV:   {ROOT / 'LLM' / 'results' / 'llm_layer_results.csv'}")
        print(f"  TTS CSV:   {ROOT / 'TTS' / 'results' / 'tts_layer_results.csv'}")
        print(f"  System CSV:{ROOT / 'System' / 'results' / 'system_layer_results.csv'}")
        return


if __name__ == "__main__":
    main()
