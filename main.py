from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from controller_audit import append_session_audit

PROJECT_ROOT = Path(__file__).resolve().parent
GESTURE_MAIN = PROJECT_ROOT / "Gesture_Architecture" / "main.py"
VOICE_MAIN = PROJECT_ROOT / "Voice_Architecture" / "main.py"

ACTION_GESTURE = "gesture"
ACTION_VOICE = "voice"


def _print_menu() -> None:
    print("=== Multimodal Assistant ===\n")
    print("Choose an interaction mode:")
    print("  1 = Gesture control")
    print("  2 = Voice assistant")
    print("  3 = Exit")


def _run_architecture(action: str, entry_script: Path, workdir: Path) -> None:
    if not entry_script.is_file():
        print(f"Error: entry script not found: {entry_script}")
        append_session_audit(action, "Session error", "error")
        return

    print(f"\nStarting {action}...\n")
    try:
        result = subprocess.run(
            [sys.executable, str(entry_script)],
            cwd=str(workdir),
            check=False,
        )
        status = "ok" if result.returncode == 0 else "error"
    except OSError as exc:
        print(f"Error: could not run architecture ({exc})")
        status = "error"

    row_id = append_session_audit(action, "CLI session", status)
    audit_path = PROJECT_ROOT / "controller_auditlog.csv"
    print(f"\n[{action}] finished (status={status}, audit id={row_id}).")
    print(f"Controller audit log: {audit_path}\n")


def main() -> None:
    while True:
        _print_menu()
        choice = input("Enter choice [1/2/3] (default 3): ").strip() or "3"
        print()

        if choice == "1":
            _run_architecture(ACTION_GESTURE, GESTURE_MAIN, GESTURE_MAIN.parent)
        elif choice == "2":
            _run_architecture(ACTION_VOICE, VOICE_MAIN, VOICE_MAIN.parent)
        elif choice == "3":
            print("Goodbye.")
            return
        else:
            print("Invalid choice. Please enter 1, 2, or 3.\n")


if __name__ == "__main__":
    main()
