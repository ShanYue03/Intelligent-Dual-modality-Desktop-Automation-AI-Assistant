"""ChatGPT: open, type, send."""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .focus import focus_automation_page


def chatgpt_open(page: "Page") -> None:
    page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=30000)
    focus_automation_page(page)


def chatgpt_type_and_send(page: "Page", text: str) -> Tuple[bool, str]:
    try:
        focus_automation_page(page)
        page.wait_for_timeout(1200)
        selectors = [
            "#prompt-textarea",
            "textarea[data-id='root']",
            "textarea",
            "div[contenteditable='true']",
        ]
        last_err = ""
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=8000)
                loc.click()
                loc.fill(text)
                page.keyboard.press("Enter")
                page.wait_for_timeout(800)
                return True, "ok"
            except Exception as e:
                last_err = str(e)
        return False, last_err or "no_textarea"
    except Exception as e:
        return False, str(e)


def chatgpt_send_only(page: "Page") -> Tuple[bool, str]:
    try:
        focus_automation_page(page)
        page.keyboard.press("Enter")
        return True, "ok"
    except Exception as e:
        return False, str(e)
