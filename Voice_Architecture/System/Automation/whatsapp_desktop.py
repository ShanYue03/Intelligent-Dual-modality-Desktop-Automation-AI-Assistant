"""WhatsApp Desktop automation helpers (Windows).

Primary strategy:
- launch/focus WhatsApp Desktop window
- select chat via Ctrl+F search
- type message (without send)
- send current message separately

This module intentionally uses keyboard-driven automation for stability across
app versions and UI layouts. It avoids fixed screen coordinates.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional, Tuple

try:
    import pyautogui  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]

try:
    import pygetwindow as gw  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    gw = None  # type: ignore[assignment]

SITE_ID = "whatsapp"
CAPABILITIES: tuple[str, ...] = (
    "open",
    "focus",
    "search_chat",
    "select_chat",
    "select_chat_index",
    "type_text",
    "clear_search",
    "clear_message",
    "send",
)


def available() -> bool:
    return pyautogui is not None


def _activate_whatsapp_window() -> bool:
    if gw is None:
        return False
    titles = ("WhatsApp", "Whatsapp", "WhatsApp Beta")
    for title in titles:
        wins = gw.getWindowsWithTitle(title)
        if not wins:
            continue
        win = wins[0]
        try:
            if getattr(win, "isMinimized", False):
                win.restore()
            win.activate()
            time.sleep(0.25)
            return True
        except Exception:
            continue
    return False


def open_whatsapp_desktop() -> Tuple[bool, str]:
    """Launch WhatsApp Desktop and bring its window to front."""
    if pyautogui is None:
        return False, "no_pyautogui"
    for uri in ("whatsapp://", "ms-windows-store://pdp/?productid=9NKSQGP7F2NH"):
        try:
            os.startfile(uri)
            time.sleep(1.8)
            if _activate_whatsapp_window():
                return True, "ok"
            return True, "launched_no_window"
        except OSError:
            continue
    try:
        subprocess.Popen(
            [
                "explorer.exe",
                "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
            ],
            cwd=os.environ.get("SystemRoot", r"C:\Windows"),
        )
        time.sleep(2.0)
        if _activate_whatsapp_window():
            return True, "ok"
        return True, "launched_no_window"
    except OSError as e:
        return False, str(e)


def focus_whatsapp_desktop() -> Tuple[bool, str]:
    if _activate_whatsapp_window():
        return True, "ok"
    return False, "window_not_found"


def _type_or_paste_text(text: str, *, interval: float = 0.03) -> Tuple[bool, str]:
    """
    Type ASCII text directly; paste non-ASCII (e.g. Chinese) via clipboard.

    ``pyautogui.typewrite`` can miss CJK characters with IME-dependent desktop apps.
    Clipboard paste is Unicode-safe and limited to WhatsApp text-entry paths.
    """
    if pyautogui is None:
        return False, "no_pyautogui"
    if text.isascii():
        pyautogui.typewrite(text, interval=interval)
        return True, "ok"
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            # Keep the pasted content on clipboard for this turn; restoring immediately can
            # race with app paste handling and re-insert stale previous text.
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
            return True, "ok"
        finally:
            root.destroy()
    except Exception as e:
        return False, str(e)


def search_chat(query: str) -> Tuple[bool, str]:
    """Open chat search, type query, leave results visible (no Enter — does not open a chat)."""
    if pyautogui is None:
        return False, "no_pyautogui"
    name = (query or "").strip()
    if not name:
        return False, "empty_chat_name"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    try:
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.25)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        ok, note = _type_or_paste_text(name, interval=0.03)
        if not ok:
            return False, note
        time.sleep(0.2)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def select_chat(chat_name: str) -> Tuple[bool, str]:
    """Open search, type name, Enter — opens first matching chat (programmatic use)."""
    ok, note = search_chat(chat_name)
    if not ok:
        return False, note
    try:
        if pyautogui is None:
            return False, "no_pyautogui"
        pyautogui.press("enter")
        time.sleep(0.2)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def clear_chats_search_sidebar() -> Tuple[bool, str]:
    """Clear the Chats search field and exit search mode.

    Uses **one** Ctrl+F to focus the sidebar search (required when focus is in the
    conversation pane, where Esc alone does not clear the left search box).
    Then Ctrl+A, Backspace, and Esc to leave search without leaving the query stuck.
    """
    if pyautogui is None:
        return False, "no_pyautogui"
    try:
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.28)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.1)
        pyautogui.press("escape")
        time.sleep(0.12)
        pyautogui.press("escape")
        return True, "ok"
    except Exception as e:
        return False, str(e)


def clear_search() -> Tuple[bool, str]:
    """Clear chats search text and dismiss search UI (works after opening a chat)."""
    if pyautogui is None:
        return False, "no_pyautogui"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    return clear_chats_search_sidebar()


def select_chat_index(index: int, *, search_layout: bool = False) -> Tuple[bool, str]:
    """Select Nth visible chat from the left list using screen-relative click (1-based).

    When ``search_layout`` is True (after ``search_chat``), the first result sits one
    row lower than in the default list; an extra row offset is applied.
    """
    if pyautogui is None:
        return False, "no_pyautogui"
    if index not in (1, 2, 3):
        return False, "unsupported_index"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    try:
        w, h = pyautogui.size()
        x = int(w * 0.16)
        first_y = int(h * 0.29)
        row_step = int(h * 0.09)
        row_offset = (index - 1) + (1 if search_layout else 0)
        y = first_y + row_offset * row_step
        pyautogui.click(x, y)
        time.sleep(0.2)
        return True, f"ok_index_{index}"
    except Exception as e:
        return False, str(e)


def type_message(text: str) -> Tuple[bool, str]:
    if pyautogui is None:
        return False, "no_pyautogui"
    body = (text or "").strip()
    if not body:
        return False, "empty_message"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    try:
        ok, note = _type_or_paste_text(body, interval=0.02)
        if not ok:
            return False, note
        return True, "ok"
    except Exception as e:
        return False, str(e)


def clear_message() -> Tuple[bool, str]:
    """Clear current draft message in the compose box (best effort)."""
    if pyautogui is None:
        return False, "no_pyautogui"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    try:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        return True, "ok"
    except Exception as e:
        return False, str(e)


def send_message() -> Tuple[bool, str]:
    if pyautogui is None:
        return False, "no_pyautogui"
    ok, note = focus_whatsapp_desktop()
    if not ok:
        return False, note
    try:
        pyautogui.press("enter")
        return True, "ok"
    except Exception as e:
        return False, str(e)
