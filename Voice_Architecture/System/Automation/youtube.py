"""YouTube: search, play first result, pause/resume via system media key (session_ops)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .focus import focus_automation_page


def youtube_goto_home(page: "Page") -> None:
    page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=30000)
    focus_automation_page(page)


def youtube_search(page: "Page", query: str) -> Tuple[bool, str]:
    try:
        focus_automation_page(page)
        page.wait_for_timeout(800)
        box = page.locator('input[name="search_query"]').first
        box.wait_for(state="visible", timeout=15000)
        box.click()
        box.fill("")
        box.fill(query)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def youtube_play_first_video(page: "Page") -> Tuple[bool, str]:
    try:
        focus_automation_page(page)
        sel = "ytd-video-renderer a#thumbnail, ytd-video-renderer a#video-title"
        loc = page.locator(sel).first
        loc.wait_for(state="visible", timeout=15000)
        loc.click(timeout=15000)
        page.wait_for_timeout(1500)
        return True, "ok"
    except Exception as e:
        return False, str(e)


# In-player, each arrow key is typically ~5%; two presses per voice command => ~10% total.
_YT_VOLUME_KEY_STEPS = 2


def _main_youtube_video(page: "Page"):
    """``Locator`` for the primary HTML5 ``<video>`` (use ``.press``; never ``.click`` here)."""
    return page.locator(
        "ytd-player video, video.html5-main-video, #movie_player video, ytd-shorts video, video"
    ).first


def youtube_volume_step(page: "Page", direction: int) -> Tuple[bool, str]:
    """
    In-player volume change. Route Arrow Up/Down to the ``<video>`` node via
    ``locator.press`` — you get correct shortcut handling without a **click** on
    the video (a click would toggle play/pause).
    """
    if direction not in (-1, 1):
        return False, "bad_direction"
    key = "ArrowUp" if direction > 0 else "ArrowDown"
    try:
        focus_automation_page(page)
        page.wait_for_timeout(120)
        vid = _main_youtube_video(page)
        vid.wait_for(state="visible", timeout=5000)
        for _ in range(_YT_VOLUME_KEY_STEPS):
            vid.press(key)
            page.wait_for_timeout(60)
        return True, "ok"
    except Exception as e:
        el = str(e).lower()
        if "timeout" in el or "waiting for" in el:
            return False, "no_video_player"
        return False, str(e)
