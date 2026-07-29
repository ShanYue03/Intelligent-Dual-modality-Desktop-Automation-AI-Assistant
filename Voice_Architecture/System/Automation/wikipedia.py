"""Wikipedia portal: open home, search (CDP-attached Edge)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

from .focus import focus_automation_page

if TYPE_CHECKING:
    from playwright.sync_api import Page

SITE_ID = "wikipedia"
CAPABILITIES: tuple[str, ...] = ("open", "search")

HOME_URL = "https://www.wikipedia.org/"

# Delays for search (roughly 2–3s interaction budget; tweak per site here).
_SETTLE_MS = 300
_VISIBLE_PRIMARY_MS = 2300
_VISIBLE_FALLBACK_MS = 2000
_AFTER_ENTER_MS = 450


def available() -> bool:
    return True


def wikipedia_open(page: "Page") -> None:
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
    focus_automation_page(page)


def _search_candidates() -> List[Tuple[str, int]]:
    return [
        ("input#searchInput", _VISIBLE_PRIMARY_MS),
        ("input[name='search']", _VISIBLE_FALLBACK_MS),
        ("#searchform input[type='search']", _VISIBLE_FALLBACK_MS),
    ]


def wikipedia_search(page: "Page", query: str) -> Tuple[bool, str]:
    q = (query or "").strip()
    if not q:
        return False, "empty_query"
    try:
        focus_automation_page(page)
        page.wait_for_timeout(_SETTLE_MS)
        last_err = ""
        for sel, ms in _search_candidates():
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=ms)
                loc.click()
                loc.fill("")
                loc.fill(q)
                page.keyboard.press("Enter")
                page.wait_for_timeout(_AFTER_ENTER_MS)
                return True, "ok"
            except Exception as e:
                last_err = str(e)
                continue
        return False, last_err or "no_search_box"
    except Exception as e:
        return False, str(e)
