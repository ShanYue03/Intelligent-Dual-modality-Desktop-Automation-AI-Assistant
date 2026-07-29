"""
Site-specific automation (voice-driven actions in an attached browser).

Requires Microsoft Edge started manually with remote debugging, e.g.:

  msedge.exe --remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\\VoiceAssistantEdgeCDP

Then set VOICE_ASSISTANT_CDP_URL=http://127.0.0.1:9222 (default).

Sites with implemented handlers: youtube, chatgpt, wikipedia, google_maps, google_news,
whatsapp_desktop.

All site modules use ``Automation/focus.py`` (``focus_automation_page``) so the
automation tab and Edge window are raised after navigation and actions, same as
the initial CDP attach in ``browser_control``.
"""

from __future__ import annotations

from typing import AbstractSet, FrozenSet

# Sites that have Python handlers under this package
_IMPLEMENTED: FrozenSet[str] = frozenset(
    {"youtube", "chatgpt", "wikipedia", "google_maps", "google_news", "whatsapp"}
)

# Sites registered for future / partial support
_REGISTERED: FrozenSet[str] = frozenset(
    {"youtube", "chatgpt", "wikipedia", "google_news", "google_maps", "whatsapp"}
)


def registered_sites() -> AbstractSet[str]:
    return _REGISTERED


def automation_implemented(site: str) -> bool:
    """True if we have tailored automation code for this site id."""
    return site.lower() in _IMPLEMENTED


def automation_registered(site: str) -> bool:
    """True if the site name is known in the automation registry (may be stub)."""
    return site.lower().replace(" ", "_") in _REGISTERED or site.lower() in _REGISTERED


__all__ = [
    "registered_sites",
    "automation_implemented",
    "automation_registered",
]
