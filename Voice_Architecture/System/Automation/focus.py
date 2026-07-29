"""
Bring the automation tab and (on Windows) the Edge window to the foreground.

Uses ``page.bring_to_front()`` then ``System.win_edge_focus.bring_edge_to_foreground``
(SetForegroundWindow + AttachThreadInput). Used by ``PlaywrightBrowser._ensure`` and
by site modules (YouTube, ChatGPT, …) after navigation or before each action.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


def _env_flag(name: str, default: bool = True) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def focus_automation_page(page: "Page") -> None:
    """Activate the page tab and raise Edge on Windows (no-op if disabled via env)."""
    if not _env_flag("VOICE_ASSISTANT_CDP_BRING_TO_FRONT", True):
        return
    try:
        page.bring_to_front()
    except Exception:
        pass
    if sys.platform == "win32":
        from ..win_edge_focus import bring_edge_to_foreground

        try:
            bring_edge_to_foreground()
        except Exception:
            pass
