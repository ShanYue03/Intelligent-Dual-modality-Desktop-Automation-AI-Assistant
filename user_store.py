import csv
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_USER = "Lee"
USERS_CSV_HEADERS = ["timestamp", "name"]
DEFAULT_USERS_CSV = Path(__file__).resolve().parent / "users.csv"


def _ensure_users_csv(csv_path: Path) -> None:
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(USERS_CSV_HEADERS)
            writer.writerow([timestamp, DEFAULT_USER])


def get_current_user_name(csv_path: Path | str | None = None) -> str:
    path = Path(csv_path) if csv_path else DEFAULT_USERS_CSV
    _ensure_users_csv(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return DEFAULT_USER
    name = (rows[-1].get("name") or "").strip()
    return name or DEFAULT_USER


def save_user_name(name: str, csv_path: Path | str | None = None) -> str:
    path = Path(csv_path) if csv_path else DEFAULT_USERS_CSV
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("name must not be empty")
    _ensure_users_csv(path)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([timestamp, cleaned])
    return cleaned
