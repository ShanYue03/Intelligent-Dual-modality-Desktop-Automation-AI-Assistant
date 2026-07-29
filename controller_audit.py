import csv
from datetime import datetime, timezone
from pathlib import Path

from user_store import DEFAULT_USER, get_current_user_name

CSV_HEADERS = [
    "id",
    "user",
    "timestamp",
    "action",
    "status",
    "response_time",
    "cpu_utilization",
    "memory_usage",
]
DEFAULT_CSV = Path(__file__).resolve().parent / "controller_auditlog.csv"


def _next_id(csv_path: Path) -> int:
    if not csv_path.exists():
        return 1
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        return 1
    try:
        return max(int(row[0]) for row in rows[1:] if row and row[0].isdigit()) + 1
    except ValueError:
        return len(rows)


def _migrate_csv_headers(csv_path: Path) -> None:
    """Add missing columns to legacy audit files."""
    if not csv_path.exists():
        return
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return
    if all(column in headers for column in CSV_HEADERS):
        return

    rows: list[list[str]] = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            migrated = [row.get(column, "") for column in CSV_HEADERS]
            user_idx = CSV_HEADERS.index("user")
            if not migrated[user_idx]:
                migrated[user_idx] = DEFAULT_USER
            rows.append(migrated)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        writer.writerows(rows)


def _ensure_csv(csv_path: Path) -> None:
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADERS)
        return
    _migrate_csv_headers(csv_path)


def _title_for_mode(mode: str) -> tuple[str, str]:
    """Return (mode_key, display title) for voice or gesture."""
    mode_key = mode.strip().lower()
    if mode_key.startswith("gesture"):
        return "gesture", "Gesture Control"
    return "voice", "Voice Assistant"


def _capitalize_first_word(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


def format_audit_action(mode: str, first_command: str) -> str:
    """Build action column, e.g. 'Voice Assistant: Open YouTube'."""
    _, title = _title_for_mode(mode)
    command = first_command.strip()
    if not command:
        return title
    return f"{title}: {_capitalize_first_word(command)}"


def format_activity_display(action: str) -> tuple[str, str]:
    """Return (type, label) e.g. ('voice', 'Voice Assistant: Open YouTube')."""
    raw = (action or "").strip()
    if not raw:
        return "voice", "Activity"

    lower = raw.lower()
    if lower.startswith("gesture"):
        mode, title = "gesture", "Gesture Control"
    elif lower.startswith("voice"):
        mode, title = "voice", "Voice Assistant"
    else:
        return "voice", raw

    detail = ""
    for sep in (":", "|"):
        if sep in raw:
            detail = raw.split(sep, 1)[1].strip()
            break

    if not detail:
        return mode, title

    return mode, f"{title}: {_capitalize_first_word(detail)}"


def _format_optional_float(value: float | None, *, precision: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{precision}f}"


def append_controller_audit(
    action: str,
    status: str,
    csv_path: Path | str | None = None,
    *,
    user: str | None = None,
    response_time_ms: float | None = None,
    cpu_utilization: float | None = None,
    memory_usage: float | None = None,
) -> int:
    """
    Append one controller session row. Returns the assigned id.
    response_time_ms: voice latency in ms (after recording until before TTS).
    cpu_utilization / memory_usage: percentages for this action's session window.
    """
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    _ensure_csv(path)
    row_id = _next_id(path)
    user_name = (user or get_current_user_name()).strip() or DEFAULT_USER
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [
                row_id,
                user_name,
                timestamp,
                action,
                status,
                _format_optional_float(response_time_ms, precision=2),
                _format_optional_float(cpu_utilization),
                _format_optional_float(memory_usage),
            ]
        )
    return row_id


def append_session_audit(
    mode: str,
    first_command: str,
    status: str,
    csv_path: Path | str | None = None,
    *,
    user: str | None = None,
    response_time_ms: float | None = None,
    cpu_utilization: float | None = None,
    memory_usage: float | None = None,
) -> int:
    """Log session with mode and first command in the action column."""
    return append_controller_audit(
        format_audit_action(mode, first_command),
        status,
        csv_path,
        user=user,
        response_time_ms=response_time_ms,
        cpu_utilization=cpu_utilization,
        memory_usage=memory_usage,
    )


def read_audit_rows(
    csv_path: Path | str | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, str]]:
    path = Path(csv_path) if csv_path else DEFAULT_CSV
    if not path.exists():
        return []
    _migrate_csv_headers(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader if row.get("id")]
    if limit is not None and limit > 0:
        rows = rows[-limit:]
    return rows


def _parse_optional_float(row: dict[str, str], key: str) -> float | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_response_time_ms(row: dict[str, str]) -> float | None:
    return _parse_optional_float(row, "response_time")


def parse_cpu_utilization(row: dict[str, str]) -> float | None:
    return _parse_optional_float(row, "cpu_utilization")


def parse_memory_usage(row: dict[str, str]) -> float | None:
    return _parse_optional_float(row, "memory_usage")


def is_voice_audit_row(action: str) -> bool:
    lower = (action or "").lower()
    return lower.startswith("voice") or "voice assistant" in lower


def is_gesture_audit_row(action: str) -> bool:
    lower = (action or "").lower()
    return lower.startswith("gesture") or "gesture control" in lower
