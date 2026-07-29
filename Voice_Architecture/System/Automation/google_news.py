"""Google News (Malaysia locale): open home, search via URL (CDP-attached Edge)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
from urllib.parse import quote_plus

from .focus import focus_automation_page

if TYPE_CHECKING:
    from playwright.sync_api import Page

SITE_ID = "google_news"
CAPABILITIES: tuple[str, ...] = ("open", "search")

HOME_URL = "https://news.google.com/home?hl=en-MY&gl=MY&ceid=MY:en"


def _search_url(query: str) -> str:
    q = (query or "").strip()
    return (
        "https://news.google.com/search?"
        f"q={quote_plus(q)}&hl=en-MY&gl=MY&ceid=MY%3Aen"
    )


def available() -> bool:
    return True


def google_news_open(page: "Page") -> None:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
    focus_automation_page(page)


def google_news_search(page: "Page", query: str) -> Tuple[bool, str]:
    q = (query or "").strip()
    if not q:
        return False, "empty_query"
    try:
        focus_automation_page(page)
        page.goto(_search_url(q), wait_until="domcontentloaded", timeout=45000)
        focus_automation_page(page)
        return True, "ok"
    except Exception as e:
        return False, str(e)
