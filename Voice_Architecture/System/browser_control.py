"""
Playwright CDP attachment to a manually running Microsoft Edge (no browser launch).

Start Edge first, e.g. PowerShell:

  & "${env:ProgramFiles(x86)}\\Microsoft\\Edge\\Application\\msedge.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="$env:LOCALAPPDATA\\VoiceAssistantEdgeCDP"

Then this module connects with connect_over_cdp (avoids Playwright launching a new
automation browser and the googlevideo 403 issues from that path).

After a successful attach, ``focus_automation_page`` runs: Playwright
``bring_to_front()`` on the tab, then on Windows ``System.win_edge_focus.bring_edge_to_foreground``
so the Edge window is raised (same path as YouTube / ChatGPT automation actions).

Requires: pip install playwright

Environment:
  VOICE_ASSISTANT_CDP_URL — WebSocket/HTTP CDP endpoint (default http://127.0.0.1:9222)
  VOICE_ASSISTANT_CDP_BRING_TO_FRONT — set to 0/false/no to skip focusing Edge
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from .Automation import chatgpt as aut_chatgpt
from .Automation import google_maps as aut_google_maps
from .Automation import google_news as aut_google_news
from .Automation.focus import focus_automation_page
from .Automation import wikipedia as aut_wikipedia
from .Automation import youtube as aut_youtube

_CDP_URL = os.environ.get("VOICE_ASSISTANT_CDP_URL", "http://127.0.0.1:9222").strip()

# Runs in new documents on this context (must be on BrowserContext).
_WEBDRIVER_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined,
});
"""


class PlaywrightBrowser:
    """Attached Edge via CDP: one context + primary page for voice automation."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @property
    def page(self):
        return self._page

    def _ensure(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright"
            ) from e
        url = _CDP_URL
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(url)
        except Exception as e:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
            raise RuntimeError(
                f"CDP connect failed ({url}). Start Edge with --remote-debugging-port "
                f"matching this URL. Underlying error: {e}"
            ) from e
        contexts = self._browser.contexts
        if not contexts:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._playwright = None
            raise RuntimeError(
                "Connected but no browser contexts — keep at least one Edge window open."
            )
        self._context = contexts[0]
        try:
            self._context.add_init_script(_WEBDRIVER_INIT_SCRIPT)
        except Exception:
            pass
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()
        focus_automation_page(self._page)
        print(
            f"[browser] Attached via CDP — {url}\n"
            "[browser] Edge brought to front (tab + Windows focus). Disconnecting the assistant does not close Edge."
        )

    def close(self) -> None:
        """Detach Playwright from Edge; does not exit the browser."""
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def goto(self, url: str, timeout_ms: int = 30000) -> None:
        self._ensure()
        self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        focus_automation_page(self._page)

    # --- YouTube (delegates to Automation/youtube.py) ---
    def youtube_home(self) -> None:
        self._ensure()
        aut_youtube.youtube_goto_home(self._page)

    def youtube_search(self, query: str) -> Tuple[bool, str]:
        self._ensure()
        return aut_youtube.youtube_search(self._page, query)

    def youtube_play_first_video(self) -> Tuple[bool, str]:
        self._ensure()
        return aut_youtube.youtube_play_first_video(self._page)

    def youtube_volume_step(self, direction: int) -> Tuple[bool, str]:
        self._ensure()
        return aut_youtube.youtube_volume_step(self._page, direction)

    # --- ChatGPT (delegates to Automation/chatgpt.py) ---
    def chatgpt_open(self) -> None:
        self._ensure()
        aut_chatgpt.chatgpt_open(self._page)

    def chatgpt_type_and_send(self, text: str) -> Tuple[bool, str]:
        self._ensure()
        return aut_chatgpt.chatgpt_type_and_send(self._page, text)

    def chatgpt_send_only(self) -> Tuple[bool, str]:
        self._ensure()
        return aut_chatgpt.chatgpt_send_only(self._page)

    # --- Google Maps ---
    def google_maps_open(self) -> None:
        self._ensure()
        aut_google_maps.google_maps_open(self._page)

    def google_maps_search(self, query: str) -> Tuple[bool, str]:
        self._ensure()
        return aut_google_maps.google_maps_search(self._page, query)

    # --- Wikipedia ---
    def wikipedia_open(self) -> None:
        self._ensure()
        aut_wikipedia.wikipedia_open(self._page)

    def wikipedia_search(self, query: str) -> Tuple[bool, str]:
        self._ensure()
        return aut_wikipedia.wikipedia_search(self._page, query)

    # --- Google News ---
    def google_news_open(self) -> None:
        self._ensure()
        aut_google_news.google_news_open(self._page)

    def google_news_search(self, query: str) -> Tuple[bool, str]:
        self._ensure()
        return aut_google_news.google_news_search(self._page, query)


def media_play_pause() -> Tuple[bool, str]:
    try:
        from pynput.keyboard import Controller, Key

        k = Controller()
        k.press(Key.media_play_pause)
        k.release(Key.media_play_pause)
        return True, "ok"
    except Exception as e:
        return False, str(e)
