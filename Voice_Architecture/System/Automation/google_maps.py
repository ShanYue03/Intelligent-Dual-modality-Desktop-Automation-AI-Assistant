"""Google Maps: open home, search by voice (CDP-attached Edge).

**Why not automate the omnibox (#searchboxinput)?**

Google Maps renders the search bar inside a complex, frequently changing UI (open/closed
shadow trees, lazy hydration, consent layers, A/B tests). Playwright often cannot
reliably find or ``fill`` the control in time even with long timeouts — that is the
typical root cause of persistent "action failed" on DOM-only approaches.

**Reliable approach:** use Maps' own search URL scheme (documented for deep links), which
loads results without driving the omnibox at all — same idea as opening a shared Maps link.
See: https://developers.google.com/maps/documentation/urls/get-started
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple
from urllib.parse import quote_plus

from .focus import focus_automation_page

if TYPE_CHECKING:
    from playwright.sync_api import Page

SITE_ID = "google_maps"
CAPABILITIES: tuple[str, ...] = ("open", "search")

HOME_URL = "https://www.google.com/maps"


def available() -> bool:
    return True


def google_maps_open(page: "Page") -> None:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
    focus_automation_page(page)


def _maps_search_url(query: str) -> str:
    """Maps URLs v1 search — ``api=1`` is required or parameters are ignored."""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query.strip())}"


def google_maps_search(page: "Page", query: str) -> Tuple[bool, str]:
    q = (query or "").strip()
    if not q:
        return False, "empty_query"
    try:
        focus_automation_page(page)
        url = _maps_search_url(q)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        focus_automation_page(page)
        return True, "ok"
    except Exception as e:
        return False, str(e)
