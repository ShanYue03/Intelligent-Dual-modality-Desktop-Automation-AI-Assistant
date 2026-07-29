"""
Windows: bring an existing Microsoft Edge top-level window to the foreground.

Playwright's page.bring_to_front() only activates a tab inside Edge; if another
app (IDE, browser, etc.) has focus, Edge may stay in the background. This module
finds a visible Edge window and calls SetForegroundWindow with the usual
AttachThreadInput workaround so focus can move across processes.

Edge is detected by **process image** (``msedge.exe``) when possible, with a
fallback to the window title containing ``Microsoft Edge`` (e.g. if process
query fails due to permissions).
"""

from __future__ import annotations

import os
import sys
from ctypes import wintypes
import ctypes


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _get_process_image_path(pid: int) -> str | None:
    """Return full path to the process executable, or None if unavailable."""
    if pid <= 0:
        return None
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value or None
    finally:
        kernel32.CloseHandle(h)
    return None


def _is_msedge_exe(path: str | None) -> bool:
    if not path:
        return False
    base = os.path.basename(path).lower()
    return base == "msedge.exe"


def bring_edge_to_foreground() -> bool:
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_RESTORE = 9
    candidates: list[tuple[int, int]] = []  # (hwnd, area)
    pid_cache: dict[int, str | None] = {}

    def _exe_for_pid(pid: int) -> str | None:
        if pid not in pid_cache:
            pid_cache[pid] = _get_process_image_path(pid)
        return pid_cache[pid]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):  # GW_OWNER — skip owned popups
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 200 or h < 200:
            return True

        ln = user32.GetWindowTextLengthW(hwnd)
        if ln > 1024:
            return True
        if ln > 0:
            buf = ctypes.create_unicode_buffer(ln + 2)
            user32.GetWindowTextW(hwnd, buf, ln + 2)
            title = buf.value or ""
        else:
            title = ""

        pid_dword = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_dword))
        pid = int(pid_dword.value)

        by_exe = _is_msedge_exe(_exe_for_pid(pid))
        by_title = "Microsoft Edge" in title
        if not (by_exe or by_title):
            return True

        candidates.append((hwnd, w * h))
        return True

    user32.EnumWindows(_enum, 0)
    if not candidates:
        return False
    hwnd = max(candidates, key=lambda x: x[1])[0]

    user32.ShowWindow(hwnd, SW_RESTORE)

    foreground = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(foreground, None)

    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)

    return True
