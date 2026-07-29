"""
System layer: rule-based OS actions (Windows).

Fast keyword + regex routing — no extra ML models. Safe URL/path handling;
no lock, shutdown, or arbitrary shell commands.

Site-specific browser automation lives under ``System/Automation/`` (YouTube, ChatGPT, …).
``system_layer`` routes open/search intents there when Playwright CDP automation applies.
"""

from __future__ import annotations

# =============================================================================
# Imports
# =============================================================================

import csv
import difflib
import os
import re
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple
from urllib.parse import quote_plus, urlparse

from . import session_ops
from .Automation import automation_implemented

# =============================================================================
# Paths, CSV logging, and screenshot output directory
# =============================================================================

LAYER_ROOT = Path(__file__).resolve().parent
RESULT_DIR = LAYER_ROOT / "results"
RESULT_CSV = RESULT_DIR / "system_layer_results.csv"
EVAL_DIR = LAYER_ROOT / "Evaluation"
EVAL_RESULT_CSV = EVAL_DIR / "system_evaluation_results.csv"
SCREENSHOT_DIR = LAYER_ROOT / "screenshots"

RESULT_DIR.mkdir(parents=True, exist_ok=True)
EVAL_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Pending yes/no after a fuzzy "did you mean …?" (cleared on confirm, deny, or new command)
_PENDING_CONFIRM: Optional[Dict[str, str]] = None

CSV_HEADER = [
    "timestamp_utc",
    "voice_language",
    "input_text",
    "intent",
    "detail",
    "reply_preview",
    "latency_s",
    "status",
    "note",
]

EVAL_CSV_HEADER = [
    "id",
    "language",
    "message",
    "latency",
    "results",
]

_EVAL_NEXT_ID: Optional[int] = None

# =============================================================================
# Static lookups: websites, apps, and user folders (used by intent handlers)
# =============================================================================

SITE_ALIASES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "outlook": "https://outlook.live.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://twitter.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
}

# App token -> executable name or ms-settings URI (validated before start)
APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "settings": "ms-settings:",
    "microsoft edge": "msedge",
    "edge": "msedge",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "spotify": "spotify",
    "vscode": "code",
    "visual studio code": "code",
    "word": "winword",
    "microsoft word": "winword",
    "ms word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "ms excel": "excel",
    "powerpoint": "powerpnt",
    "microsoft powerpoint": "powerpnt",
    "ms powerpoint": "powerpnt",
}

# Special folders under user profile (safe opens)
FOLDER_ALIASES = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}

# =============================================================================
# Compiled regex: timer and alarm phrases
# =============================================================================

_RE_TIMER = re.compile(
    r"(?:set\s+(?:a\s+)?timer|timer)\s*(?:for\s*)?"
    r"(\d+)\s*(minute|minutes|min|second|seconds|sec|hour|hours|hr|hrs)\b",
    re.I,
)
# Must end with "timer" or "countdown" to avoid matching "open 5 minutes" etc.
_RE_TIMER_SHORT = re.compile(
    r"\b(\d+)\s*(minute|minutes|min|second|seconds|sec|hour|hours|hr|hrs)\s+"
    r"(?:timer|countdown)\b",
    re.I,
)
_RE_ALARM = re.compile(
    r"(?:set\s+(?:an\s+)?alarm|alarm)\s*(?:for|at)?\s*"
    r"(\d{1,2})\s*[:.]\s*(\d{2})\s*(am|pm)?",
    re.I,
)
_RE_ALARM_SIMPLE = re.compile(
    r"(?:set\s+(?:an\s+)?alarm|alarm)\s*(?:for|at)?\s*(\d{1,2})\s*(am|pm)\b",
    re.I,
)


# =============================================================================
# Normalization, URL/path checks, safe open under user profile, and app launch
# =============================================================================


def _normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s:/.\\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _normalize_zh_text(text: str) -> str:
    """Compact Chinese text for fast rule matching."""
    t = (text or "").strip().lower()
    t = re.sub(r"[，。！？、；：“”\"'（）()【】\[\],.!?;:]", "", t)
    return re.sub(r"\s+", "", t)


def _strip_zh_fillers(text: str) -> str:
    t = _normalize_zh_text(text)
    filler_patterns = [
        r"^(请帮我|请你帮我|麻烦你帮我|麻烦你|帮我|请你|请)",
        r"^(可以帮我|可不可以帮我|能不能帮我|能不能|可不可以|可以|能否)",
        r"(一下子?|好吗|谢谢)$",
    ]
    for p in filler_patterns:
        t = re.sub(p, "", t)
    return t


def canonicalize_zh_system_command(text: str) -> str:
    """
    Map common Chinese system intents to canonical English commands.

    Returns canonical command string for matched intents, otherwise ``""``.
    Keep this allowlist-focused for safety and low latency.
    """
    zh = _strip_zh_fillers(text)
    if not zh:
        return ""

    # Session / automation stop (before media pause rules so 暂停自动化 ends session)
    if re.search(r"(停止|结束|退出|暂停).*(操作|自动化|会话)|停止助手", zh):
        return "stop automation"
    if re.fullmatch(r"(取消|不用了|算了)", zh):
        return "cancel"

    # WhatsApp session actions (desktop automation)
    m = re.search(r"(?:搜索|查找)(?:聊天|用户)(.+)$", zh)
    if m:
        q = m.group(1).strip()
        return f"search chat {q}" if q else ""
    m = re.search(r"(?:选择|打开)(?:第)?(?P<ord>一|二|三|1|2|3)(?:个)?(?:聊天|对话)", zh)
    if m:
        ord_map = {"一": "first", "1": "first", "二": "second", "2": "second", "三": "third", "3": "third"}
        ord_word = ord_map.get(m.group("ord"), "")
        if ord_word:
            return f"select {ord_word} chat"
    m = re.search(r"(?:输入|写|打字)(.+)$", zh)
    if m:
        body = m.group(1).strip()
        return f"type {body}" if body else ""
    if re.fullmatch(r"(发送|送出|发出去?)", zh):
        return "send"
    if re.search(r"(清除|清空|删除).*(搜索|查找)", zh):
        return "clear search"
    if re.search(r"(清除|清空|删除).*(消息|讯息|内容|文字)", zh):
        return "clear message"

    if re.search(
        r"(提高|增大|加大|调高).{0,6}系统音量|系统音量.{0,6}(提高|增大|加大|调高)",
        zh,
    ):
        return "increase system volume"
    if re.search(
        r"(降低|减小|调低).{0,6}系统音量|系统音量.{0,6}(降低|减小|调低)",
        zh,
    ):
        return "decrease system volume"
    # Open explicit URL in text
    m = re.search(r"(https?://[a-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+)", zh, re.I)
    if m:
        return f"open {m.group(1)}"

    # Open explicit path (Windows path after "打开路径")
    m = re.search(r"(?:打开|开启|显示)(?:文件)?路径([a-z]:\\[^\n]+)$", zh, re.I)
    if m:
        p = m.group(1).strip().rstrip("。.,)")
        return f"open path {p}"

    # Open website / app
    open_verbs = r"(打开|开启|启动|进入|前往|去到|访问|显示)"
    if re.search(open_verbs + r".*(油管|youtube)", zh):
        return "open youtube"
    if re.search(open_verbs + r".*(谷歌地图|googlemaps|地图)", zh):
        return "open google maps"
    if re.search(open_verbs + r".*(维基|wikipedia)", zh):
        return "open wikipedia"
    if re.search(open_verbs + r".*(谷歌新闻|googlenews)", zh):
        return "open google news"
    if re.search(open_verbs + r".*(谷歌|google)", zh):
        return "open google"
    if re.search(open_verbs + r".*(邮箱|gmail)", zh):
        return "open gmail"
    if re.search(open_verbs + r".*(github)", zh):
        return "open github"
    if re.search(open_verbs + r".*(outlook)", zh):
        return "open outlook"
    if re.search(open_verbs + r".*(facebook|脸书)", zh):
        return "open facebook"
    if re.search(open_verbs + r".*(twitter|推特)", zh):
        return "open twitter"
    if re.search(open_verbs + r".*(reddit)", zh):
        return "open reddit"
    if re.search(open_verbs + r".*(linkedin)", zh):
        return "open linkedin"
    if re.search(open_verbs + r".*(?:聊天gpt|聊天机器)", zh):
        return "open chatgpt"
    if re.search(open_verbs + r".*(?:whatsapp|聊天应用)", zh):
        return "open whatsapp"
    if re.search(open_verbs + r".*(记事本)", zh):
        return "open notepad"
    if re.search(open_verbs + r".*(计算器)", zh):
        return "open calculator"
    if re.search(open_verbs + r".*(画图)", zh):
        return "open paint"
    if re.search(open_verbs + r".*(edge|微软浏览器)", zh):
        return "open microsoft edge"
    if re.search(open_verbs + r".*(chrome|谷歌浏览器)", zh):
        return "open google chrome"
    if re.search(open_verbs + r".*(firefox|火狐)", zh):
        return "open firefox"
    if re.search(open_verbs + r".*(spotify)", zh):
        return "open spotify"
    if re.search(open_verbs + r".*(vscode|visualstudiocode|代码编辑器)", zh):
        return "open vscode"
    if re.search(open_verbs + r".*(word)", zh):
        return "open word"
    if re.search(open_verbs + r".*(excel)", zh):
        return "open excel"
    if re.search(open_verbs + r".*(powerpoint|ppt)", zh):
        return "open powerpoint"
    if re.search(open_verbs + r".*(资源管理器|文件管理器)", zh):
        return "open file explorer"
    if re.search(open_verbs + r".*(设置)", zh):
        return "open settings"
    if re.search(open_verbs + r".*(下载)", zh):
        return "open my downloads"
    if re.search(open_verbs + r".*(文档|文件夹文档)", zh):
        return "open my documents"
    if re.search(open_verbs + r".*(桌面)", zh):
        return "open my desktop"
    if re.search(open_verbs + r".*(图片|照片)", zh):
        return "open my pictures"
    if re.search(open_verbs + r".*(音乐)", zh):
        return "open my music"
    if re.search(open_verbs + r".*(视频|影片)", zh):
        return "open my videos"

    # Search-and-open flow
    m = re.search(r"(?:搜索|查找)(.+?)(?:并|然后)?打开(?:第?一(?:个)?结果)?$", zh)
    if m:
        q = m.group(1).strip()
        return f"search the web for {q} and open first result" if q else ""
    m = re.search(r"(?:搜索网页|网页搜索)(?:并|然后)?打开(.+)$", zh)
    if m:
        q = m.group(1).strip()
        return f"search the web and open {q}" if q else ""

    # YouTube combined search/play
    m = re.search(r"(?:在)?(?:油管|youtube)(?:上)?(?:搜索|查找|找)(.+)$", zh)
    if m:
        q = m.group(1).strip()
        return f"open youtube and search {q}" if q else "open youtube"
    m = re.search(r"(?:在)?(?:油管|youtube)(?:上)?(?:播放|看|听)(.+)$", zh)
    if m:
        q = m.group(1).strip()
        return f"open youtube and play {q}" if q else "open youtube"

    # Bare search (site-neutral): map to ``search <query>`` — not ``search the web for``,
    # so active browser sessions (YouTube / Maps / …) receive only the query text.
    m = re.search(r"(?:搜索|查找|帮我搜)(.+)$", zh)
    if m:
        q = m.group(1).strip()
        # Explicit web intent — keep global web-search phrasing
        if re.match(r"^(网页|网上|网络)", q):
            q2 = re.sub(r"^(网页|网上|网络)", "", q).lstrip("为").strip()
            return f"search the web for {q2}" if q2 else ""
        return f"search {q}" if q else ""

    # Screenshot / clipboard / media
    if re.search(r"(截图|截屏|屏幕截图|拍屏幕)", zh):
        return "take a screenshot"
    if re.fullmatch(r"(复制|拷贝)", zh):
        return "copy"
    if re.fullmatch(r"(粘贴|贴上)", zh):
        return "paste"
    # YouTube session: first search result. Must precede generic 播放 → play video; otherwise
    # ``播放第一个`` matches ``播放.*`` with optional tail and becomes ``play video`` → session
    # layer maps to ``resume`` and ``media_play_pause()`` (wrong app / other browser).
    if re.match(r"^(?:播放|放)(?:第)?一(?:个|条)?(?:视频|影片|结果)?$", zh):
        return "play first"
    # Stop-before-play: ``停止播放`` contains 播放 but must not map to resume.
    if re.search(r"暂停|停止(?:播放|音乐|视频|歌曲)|停播", zh):
        return "pause video"
    if re.search(r"(?:继续|恢复)(?:播放|音乐|视频|歌曲)?", zh):
        return "play video"
    if re.fullmatch(r"播放(?:音乐|视频|歌曲)?", zh):
        return "play video"

    # Time / date
    if "什么" in zh and "时间" in zh:
        return "what time is it"
    if "什么" in zh and "日期" in zh:
        return "what's the date"
    if re.search(r"(现在)?几点|当前时间|现在时间|现在幾點", zh):
        return "what time is it"
    if re.search(r"今天(几号|日期|星期几)|当前日期|今天幾號|今天星期幾", zh):
        return "what's the date"

    # Timer and alarm
    m = re.search(r"(\d+)\s*(秒|分钟|分|小时|钟头)\s*(计时|倒计时|定时|提醒)", zh)
    if m:
        n = m.group(1)
        u = m.group(2)
        unit = "seconds" if u == "秒" else "minutes" if u in ("分钟", "分") else "hours"
        return f"set a timer for {n} {unit}"
    m = re.search(r"(?:计时|倒计时|定时)(\d+)\s*(秒|分钟|分|小时|钟头)", zh)
    if m:
        n = m.group(1)
        u = m.group(2)
        unit = "seconds" if u == "秒" else "minutes" if u in ("分钟", "分") else "hours"
        return f"set a timer for {n} {unit}"
    m = re.search(r"(?:设置|定|设)\s*闹钟\s*(\d{1,2})[:：点](\d{1,2})?", zh)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) is not None else 0
        return f"set alarm for {h:02d}:{mi:02d}"
    m = re.search(r"(?:设置|定|设)\s*闹钟\s*(上午|早上|am|下午|晚上|pm)?\s*(\d{1,2})点(\d{1,2})?", zh)
    if m:
        ap = (m.group(1) or "").lower()
        h = int(m.group(2))
        mi = int(m.group(3)) if m.group(3) is not None else 0
        if ap in ("下午", "晚上", "pm") and h != 12:
            h += 12
        if ap in ("上午", "早上", "am") and h == 12:
            h = 0
        return f"set alarm for {h:02d}:{mi:02d}"

    return ""


def _matches_desktop_time_query(norm: str) -> bool:
    if re.search(r"\b(what'?s?\s+the\s+time|what\s+time\b|current\s+time)\b", norm):
        return True
    return "what" in norm and bool(re.search(r"\btime\b", norm))


def _matches_desktop_date_query(norm: str) -> bool:
    if re.search(r"\b(what'?s?\s+the\s+date|today'?s?\s+date|what\s+day\b)\b", norm):
        return True
    return "what" in norm and bool(re.search(r"\bdate\b", norm))


def canonicalize_en_system_command(text: str) -> str:
    """Map common English time/date queries to canonical system commands."""
    norm = _normalize(text)
    if not norm:
        return ""
    if _matches_desktop_time_query(norm):
        return "what time is it"
    if _matches_desktop_date_query(norm):
        return "what's the date"
    return ""


def system_command_hint(voice_language: str, english: str, original: str = "") -> str:
    """Local keyword map for router bypass and system dispatch (en + zh)."""
    if voice_language == "zh":
        return canonicalize_zh_system_command(original or english)
    if voice_language == "en":
        return canonicalize_en_system_command(english)
    return ""


def _safe_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc or url.startswith("https://"))
    except Exception:
        return False


def _safe_home_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path.home().resolve())
        return True
    except ValueError:
        return False


def _open_path_safe(target: Path) -> Tuple[bool, str]:
    if not target.exists():
        return False, "not_found"
    try:
        if not _safe_home_path(target):
            return False, "outside_home"
        os.startfile(str(target))
        return True, "ok"
    except OSError as e:
        return False, str(e)


def _launch_app(token: str) -> Tuple[bool, str]:
    key = token.strip().lower()
    if key not in APP_ALIASES:
        return False, "unknown_app"
    spec = APP_ALIASES[key]
    if spec.startswith("ms-settings:"):
        try:
            os.startfile(spec)
            return True, "ok"
        except OSError as e:
            return False, str(e)
    exe = shutil.which(spec) or shutil.which(spec + ".exe")
    if exe:
        try:
            os.startfile(exe)
            return True, "ok"
        except OSError as e:
            return False, str(e)
    try:
        os.startfile(spec)
        return True, "ok"
    except OSError:
        return False, "not_found"


def _open_windows_clock(uri: str = "ms-clock:") -> Tuple[bool, str]:
    """Open the Windows Clock app (Alarms & Clock). URI may include e.g. ``ms-clock:``."""
    try:
        os.startfile(uri)
        return True, "ok"
    except OSError:
        try:
            subprocess.Popen(
                [
                    "explorer.exe",
                    "shell:AppsFolder\\Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
                ],
                cwd=os.environ.get("SystemRoot", r"C:\Windows"),
            )
            return True, "ok"
        except OSError as e:
            return False, str(e)


def _fill_clock_timer_and_start(total_seconds: int) -> Tuple[bool, str, bool]:
    """
    Open the Timer view, focus the Clock window, type H:M:S, and press Enter.

    Returns ``(success, note, clock_app_reached)`` where ``clock_app_reached`` is True
    if the Clock window was opened (even if typing failed).

    There is no stable public URI to pre-fill a timer on all Windows builds, so this
    uses keyboard automation. If focus lands wrong, set env ``VOICE_ASSIST_CLOCK_TAB_PRESSES``
    (default ``6``) to match your Clock app layout.
    """
    try:
        import pyautogui  # type: ignore[import-untyped]
        import pygetwindow as gw  # type: ignore[import-untyped]
    except ImportError as e:
        return False, f"import:{e}", False

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    ts = int(max(1, min(int(total_seconds), 24 * 3600)))
    h = ts // 3600
    rem = ts % 3600
    m = rem // 60
    s = rem % 60

    opened = False
    for uri in ("ms-clock:timer", "ms-clock:"):
        ok, _ = _open_windows_clock(uri)
        if ok:
            opened = True
            break
    if not opened:
        return False, "open_failed", False

    time.sleep(2.2)
    win = None
    for title in ("Clock", "Alarms", "闹钟", "Alarm", "Alarms & Clock"):
        wins = gw.getWindowsWithTitle(title)
        if wins:
            win = wins[0]
            break
    if not win:
        return False, "no_clock_window", True

    try:
        if getattr(win, "isMinimized", False):
            win.restore()
        win.activate()
        time.sleep(0.45)
    except Exception as e:
        return False, f"activate:{e}", True

    try:
        pyautogui.hotkey("ctrl", "n")
        time.sleep(0.35)
    except Exception:
        pass

    tab_pres = int(os.environ.get("VOICE_ASSIST_CLOCK_TAB_PRESSES", "6"))
    pyautogui.press("tab", presses=max(0, tab_pres))

    def type_field(val: int) -> None:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(f"{val:02d}", interval=0.05)

    try:
        type_field(h)
        pyautogui.press("tab")
        type_field(m)
        pyautogui.press("tab")
        type_field(s)
        time.sleep(0.12)
        pyautogui.press("enter")
    except Exception as e:
        return False, f"type:{e}", True
    return True, "ok", True


def _parse_yes_no(norm: str) -> Optional[bool]:
    """Return True / False for short confirmations, or None if not a yes/no reply."""
    t = norm.strip().lower()
    if re.match(
        r"^(yes|yeah|yep|sure|ok|okay|confirm|correct|please do|go ahead|do it)\b",
        t,
    ):
        return True
    if re.match(r"^(no|nope|nah|cancel|don'?t|do not|stop|negative)\b", t):
        return False
    if t in ("是", "好", "确认", "可以", "行"):
        return True
    if t in ("不", "否", "不用", "取消", "别"):
        return False
    return None


# =============================================================================
# Timer / alarm: parse durations and wall-clock times, schedule background timers
# =============================================================================


def _duration_seconds(amount: int, unit: str) -> Optional[float]:
    u = unit.lower().rstrip("s")
    if u in ("sec", "second"):
        return float(amount)
    if u in ("min", "minute"):
        return float(amount * 60)
    if u in ("hr", "hour"):
        return float(amount * 3600)
    return None


def _parse_timer_seconds(norm: str) -> Optional[float]:
    m = _RE_TIMER.search(norm)
    if not m:
        m = _RE_TIMER_SHORT.search(norm)
    if not m:
        return None
    amt = int(m.group(1))
    unit = m.group(2)
    return _duration_seconds(amt, unit)


def _parse_alarm_datetime(norm: str) -> Optional[datetime]:
    now = datetime.now()
    m = _RE_ALARM.search(norm)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        ap = (m.group(3) or "").lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    else:
        m2 = _RE_ALARM_SIMPLE.search(norm)
        if not m2:
            return None
        h = int(m2.group(1))
        ap = m2.group(2).lower()
        mi = 0
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


# =============================================================================
# Low-level OS actions: global media key, clipboard, screenshot
# =============================================================================


def _media_play_pause() -> Tuple[bool, str]:
    try:
        from pynput.keyboard import Key, Controller

        k = Controller()
        k.press(Key.media_play_pause)
        k.release(Key.media_play_pause)
        return True, "ok"
    except Exception as e:
        return False, str(e)


_SYSTEM_VOLUME_STEP_PCT = 5


def _adjust_master_volume_percent(delta: int) -> Tuple[bool, str]:
    """Adjust default playback device master volume by ``delta`` percent (-100..100)."""
    try:
        from pycaw.pycaw import AudioUtilities
    except Exception as e:
        return False, f"import:{e}"
    try:
        dev = AudioUtilities.GetSpeakers()
        if dev is None:
            return False, "no_output_device"
        # pycaw returns ``AudioDevice`` with ``EndpointVolume``; older code used
        # ``Activate(IAudioEndpointVolume)`` which is not on this object.
        vol = dev.EndpointVolume
        cur = float(vol.GetMasterVolumeLevelScalar())
        new = max(0.0, min(1.0, cur + float(delta) / 100.0))
        vol.SetMasterVolumeLevelScalar(new, None)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _clipboard_shortcut(ctrl_key: str) -> Tuple[bool, str]:
    try:
        from pynput.keyboard import Key, Controller

        k = Controller()
        key = "c" if ctrl_key == "c" else "v"
        with k.pressed(Key.ctrl):
            k.press(key)
            k.release(key)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _screenshot_fixed() -> Tuple[bool, str, str]:
    """Capture primary monitor to PNG (mss ``mon`` is a monitor index, not a dict)."""
    try:
        import mss

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOT_DIR / f"capture_{ts}.png"
        with mss.mss() as sct:
            mon_idx = 1 if len(sct.monitors) > 1 else 0
            sct.shot(mon=mon_idx, output=str(path))
        if path.exists():
            return True, "ok", str(path)
        return False, "capture_failed", ""
    except Exception as e:
        return False, str(e), ""


# =============================================================================
# Spoken reply strings (English / Chinese) and formatter
# =============================================================================

MESSAGES = {
    "en": {
        "timer_start": "Timer set for {n} {unit}.",
        "timer_done": "Timer finished.",
        "alarm_start": "Alarm set for {when}.",
        "alarm_done": "Alarm — time's up.",
        "time": "The time is {t}.",
        "date": "Today is {d}.",
        "search_ok": "Searching the web for that now.",
        "search_fail": "I couldn't start the search. Check your connection.",
        "site_open": "Opening {name} now.",
        "site_fail": "I couldn't open that page.",
        "screenshot_ok": "Screenshot saved.",
        "screenshot_fail": "Screenshot failed.",
        "media_ok": "Sending play or pause to the active player.",
        "media_fail": "Couldn't send the media key. Focus a media app if needed.",
        "volume_up_ok": "Volume increased.",
        "volume_down_ok": "Volume decreased.",
        "volume_adjust_fail": "Could not change system volume.",
        "folder_open": "Opening your {name} folder.",
        "folder_fail": "I couldn't open that folder.",
        "app_open": "Opening {name} now.",
        "app_fail": "I couldn't find or open that application.",
        "copy_ok": "Copied.",
        "paste_ok": "Pasted.",
        "clipboard_fail": "Keyboard shortcut didn't work.",
        "url_open": "Opening that link now.",
        "no_intent": "I didn't match a system command. You can say: set a timer, take a screenshot, open YouTube, or search the web.",
        "bad_path": "That path isn't allowed or doesn't exist.",
        "clarify_open": "Did you mean to open {name}? Say yes or no.",
        "clarify_cancel": "Okay, cancelled.",
        "clock_timer_open": "Opening the Clock app. Add a timer for about {n} {unit} there.",
        "clock_timer_autostart_ok": "Started a {n} {unit} timer in the Clock app.",
        "clock_timer_autostart_partial": "Opened the Clock app. If the timer did not start, set it manually or set VOICE_ASSIST_CLOCK_TAB_PRESSES.",
        "clock_timer_open_plain": "Opening the Clock app for a timer.",
        "clock_alarm_open": "Opening the Clock app for alarms.",
        "alarm_clock_hint": "Opening the Clock app. Add an alarm for about {when} there.",
        "youtube_search_ok": "Opening YouTube with search for {query}.",
        "search_open_first_ok": "Opening the first web result for {query}.",
        "search_open_first_fallback": "Could not fetch a result link. Opened the search page for {query} instead.",
    },
    "zh": {
        "timer_start": "已设置 {n} {unit} 的计时器。",
        "timer_done": "计时结束。",
        "alarm_start": "已设置闹钟：{when}。",
        "alarm_done": "闹钟时间到了。",
        "time": "现在时间是 {t}。",
        "date": "今天是 {d}。",
        "search_ok": "正在搜索。",
        "search_fail": "无法开始搜索，请检查网络。",
        "site_open": "正在打开 {name}。",
        "site_fail": "无法打开该页面。",
        "screenshot_ok": "截图已保存。",
        "screenshot_fail": "截图失败。",
        "media_ok": "已发送播放或暂停。",
        "media_fail": "无法发送媒体键，请确保播放器在前台。",
        "volume_up_ok": "已调高音量。",
        "volume_down_ok": "已调低音量。",
        "volume_adjust_fail": "无法调节系统音量。",
        "folder_open": "正在打开 {name} 文件夹。",
        "folder_fail": "无法打开该文件夹。",
        "app_open": "正在打开 {name}。",
        "app_fail": "找不到或无法打开该程序。",
        "copy_ok": "已复制。",
        "paste_ok": "已粘贴。",
        "clipboard_fail": "快捷键未能执行。",
        "url_open": "正在打开链接。",
        "no_intent": "未识别为系统指令。你可以说：计时、截图、打开 YouTube、或网页搜索。",
        "bad_path": "路径无效或不允许。",
        "clarify_open": "你是要打开 {name} 吗？请说确认或取消。",
        "clarify_cancel": "好的，已取消。",
        "clock_timer_open": "正在打开时钟应用，请在应用里设置约 {n} {unit} 的计时器。",
        "clock_timer_autostart_ok": "已在时钟应用中开始 {n} {unit} 的计时器。",
        "clock_timer_autostart_partial": "已打开时钟应用。若未自动开始，请手动设置，或调整环境变量 VOICE_ASSIST_CLOCK_TAB_PRESSES。",
        "clock_timer_open_plain": "正在打开时钟应用以使用计时器。",
        "clock_alarm_open": "正在打开时钟应用的闹钟。",
        "alarm_clock_hint": "正在打开时钟应用，请在应用里添加约 {when} 的闹钟。",
        "youtube_search_ok": "正在打开 YouTube 并搜索：{query}。",
        "search_open_first_ok": "正在打开与 {query} 相关的第一个网页结果。",
        "search_open_first_fallback": "无法获取第一条链接，已改为打开搜索页面：{query}。",
    },
}


def _msg(lang: str, key: str, **kwargs) -> str:
    lang = "zh" if lang == "zh" else "en"
    template = MESSAGES[lang].get(key) or MESSAGES["en"][key]
    return template.format(**kwargs)


# =============================================================================
# Intent handlers: each returns (intent, detail, reply, status) or None
# =============================================================================

# --- Timer ---


def _try_timer(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    sec = _parse_timer_seconds(norm)
    if sec is None or sec <= 0:
        if re.search(
            r"\b(set\s+(?:a\s+)?timer|open\s+(?:the\s+)?(?:clock\s+)?timer|timer\s+app|"
            r"start\s+(?:a\s+)?timer)\b",
            norm,
        ):
            ok, note = _open_windows_clock("ms-clock:")
            if ok:
                return ("timer", "clock", _msg(lang, "clock_timer_open_plain"), "ok")
            return ("timer", note, _msg(lang, "clock_timer_open_plain"), note)
        return None
    if sec > 24 * 3600:
        return None
    unit_word = "seconds" if sec < 60 else ("minutes" if sec < 3600 else "hours")
    n = int(sec) if sec < 60 else int(sec // 60) if sec < 3600 else round(sec / 3600, 1)
    auto_ok, auto_note, clock_reached = _fill_clock_timer_and_start(int(sec))
    if auto_ok:
        return (
            "timer",
            f"{sec:.0f}s",
            _msg(lang, "clock_timer_autostart_ok", n=n, unit=unit_word),
            "ok",
        )
    if not clock_reached and str(auto_note).startswith("import:"):
        ok, note = _open_windows_clock("ms-clock:")
        if ok:
            return (
                "timer",
                f"{sec:.0f}s",
                _msg(lang, "clock_timer_open", n=n, unit=unit_word),
                "ok",
            )
        return ("timer", note, _msg(lang, "clock_timer_open_plain"), note)
    if clock_reached:
        return (
            "timer",
            f"{sec:.0f}s:{auto_note}",
            _msg(lang, "clock_timer_autostart_partial"),
            "partial",
        )
    ok, note = _open_windows_clock("ms-clock:")
    if ok:
        return (
            "timer",
            f"{sec:.0f}s:{auto_note}",
            _msg(lang, "clock_timer_open", n=n, unit=unit_word),
            "partial",
        )
    return ("timer", note, _msg(lang, "clock_timer_open_plain"), note)


# --- Alarm ---


def _try_alarm(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if "alarm" not in norm and "wake me" not in norm:
        return None
    target = _parse_alarm_datetime(norm)
    if target is None:
        return None
    when_s = target.strftime("%H:%M")
    ok, note = _open_windows_clock("ms-clock:alarms")
    if not ok:
        ok, note = _open_windows_clock("ms-clock:")
    if ok:
        return (
            "alarm",
            when_s,
            _msg(lang, "alarm_clock_hint", when=when_s),
            "ok",
        )
    return ("alarm", note, _msg(lang, "clock_alarm_open"), note)


# --- Current time and date (read-only) ---


def _try_time_date(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if _matches_desktop_time_query(norm):
        t = datetime.now().strftime("%H:%M:%S")
        return ("time", t, _msg(lang, "time", t=t), "ok")
    if _matches_desktop_date_query(norm):
        d = datetime.now().strftime("%Y-%m-%d")
        return ("date", d, _msg(lang, "date", d=d), "ok")
    return None


# --- Web search and opening URLs / sites ---


def _extract_search_query(norm: str) -> Optional[str]:
    patterns: List[Pattern[str]] = [
        re.compile(r"search\s+(?:the\s+)?(?:web\s+)?for\s+(.+)", re.I),
        re.compile(r"look\s+up\s+(.+)", re.I),
        re.compile(r"find\s+(?:information\s+)?(?:on|about)\s+(.+)", re.I),
        re.compile(r"google\s+(.+)", re.I),
    ]
    for p in patterns:
        m = p.search(norm)
        if m:
            q = m.group(1).strip()
            if len(q) >= 2:
                return q
    return None


def _first_web_result_url(query: str) -> Optional[str]:
    """Return first organic result URL for ``query`` (DuckDuckGo text search)."""
    q = (query or "").strip()
    if len(q) < 1:
        return None
    try:
        from duckduckgo_search import DDGS  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=5, region="wt-wt"):
                if not isinstance(r, dict):
                    continue
                href = (r.get("href") or r.get("url") or "").strip()
                if href and _safe_url(href):
                    return href
        return None
    except Exception:
        return None


def _automation_site_from_open_phrase(q: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Map trailing phrase of 'search the web and open …' to (site_id, optional_inner_query).

    Examples: 'youtube' → (youtube, None); 'youtube for cats' → (youtube, 'cats');
    'chat gpt' → (chatgpt, None).
    """
    t = (q or "").strip().lower()
    t = re.sub(r"^the\s+", "", t)
    if re.fullmatch(r"yt|youtube|youtube\.com", t):
        return ("youtube", None)
    m = re.match(r"youtube(?:\.com)?\s+for\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        return ("youtube", inner) if inner else ("youtube", None)
    m = re.match(r"youtube(?:\.com)?\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("youtube", inner)
    if re.fullmatch(r"chatgpt|chat\s*gpt|chatgpt\.com", t):
        return ("chatgpt", None)
    m = re.match(r"chat\s*gpt(?:\.com)?\s+for\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("chatgpt", inner)
    if re.fullmatch(r"wikipedia|wiki", t):
        return ("wikipedia", None)
    m = re.match(r"wikipedia\s+for\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("wikipedia", inner)
    m = re.match(r"wikipedia\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("wikipedia", inner)
    if re.fullmatch(r"google\s+maps|maps\.google", t):
        return ("google_maps", None)
    m = re.match(r"google\s+maps\s+for\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("google_maps", inner)
    m = re.match(r"google\s+maps\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("google_maps", inner)
    if re.fullmatch(r"google\s+news|googlenews", t):
        return ("google_news", None)
    m = re.match(r"google\s+news\s+for\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("google_news", inner)
    m = re.match(r"google\s+news\s+(.+)$", t, re.I)
    if m:
        inner = m.group(1).strip()
        if inner:
            return ("google_news", inner)
    return None


def _try_start_automation_for_open_phrase(q: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """If phrase names an automation-backed site, start CDP session (and optional YouTube search)."""
    parsed = _automation_site_from_open_phrase(q)
    if not parsed:
        return None
    site, inner = parsed
    if not session_ops.playwright_available():
        return None
    if site == "youtube" and automation_implemented("youtube"):
        ok, msg = session_ops.start_youtube_session(lang)
        if not ok:
            return ("session_youtube", "youtube", msg, "fail")
        if inner:
            turn = session_ops.run_session_turn(lang, f"search {inner}")
            reply = str(turn.get("reply", "")).strip() or msg
            return ("session_youtube", (inner or q)[:120], reply, "ok")
        return ("session_youtube", q[:120], msg, "ok")
    if site == "chatgpt" and automation_implemented("chatgpt"):
        ok, msg = session_ops.start_chatgpt_session(lang)
        if not ok:
            return ("session_chatgpt", "chatgpt", msg, "fail")
        return ("session_chatgpt", q[:120], msg, "ok")
    if site == "wikipedia" and automation_implemented("wikipedia"):
        ok, msg = session_ops.start_wikipedia_session(lang)
        if not ok:
            return ("session_wikipedia", "wikipedia", msg, "fail")
        if inner:
            turn = session_ops.run_session_turn(lang, f"search {inner}")
            reply = str(turn.get("reply", "")).strip() or msg
            return ("session_wikipedia", (inner or q)[:120], reply, "ok")
        return ("session_wikipedia", q[:120], msg, "ok")
    if site == "google_maps" and automation_implemented("google_maps"):
        ok, msg = session_ops.start_google_maps_session(lang)
        if not ok:
            return ("session_google_maps", "google_maps", msg, "fail")
        if inner:
            turn = session_ops.run_session_turn(lang, f"search {inner}")
            reply = str(turn.get("reply", "")).strip() or msg
            return ("session_google_maps", (inner or q)[:120], reply, "ok")
        return ("session_google_maps", q[:120], msg, "ok")
    if site == "google_news" and automation_implemented("google_news"):
        ok, msg = session_ops.start_google_news_session(lang)
        if not ok:
            return ("session_google_news", "google_news", msg, "fail")
        if inner:
            turn = session_ops.run_session_turn(lang, f"search {inner}")
            reply = str(turn.get("reply", "")).strip() or msg
            return ("session_google_news", (inner or q)[:120], reply, "ok")
        return ("session_google_news", q[:120], msg, "ok")
    return None


def _try_web_search_open_first(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """
    ``search the web and open …`` → automation session if target is YouTube/ChatGPT, else
    open first DuckDuckGo result in default browser.
    """
    if re.search(r"\b(open|launch|start)\s+google\s+chrome\b", norm):
        return None
    patterns = [
        re.compile(r"search\s+the\s+web\s+and\s+open\s+(.+)", re.I),
        re.compile(
            r"search\s+the\s+web\s+for\s+(.+?)\s+and\s+open(?:\s+(?:the\s+)?first(?:\s+result)?)?\s*$",
            re.I,
        ),
        re.compile(
            r"search\s+for\s+(.+?)\s+and\s+open\s+(?:the\s+)?first(?:\s+result)?\s*$",
            re.I,
        ),
    ]
    for p in patterns:
        m = p.search(norm)
        if not m:
            continue
        q = m.group(1).strip()
        q = re.sub(r"\b(please|now)\s*$", "", q).strip()
        q = re.sub(r"^for\s+", "", q, flags=re.I).strip()
        if len(q) < 1:
            return None
        auto = _try_start_automation_for_open_phrase(q, lang)
        if auto is not None:
            return auto
        url = _first_web_result_url(q)
        serp = "https://www.google.com/search?q=" + quote_plus(q)
        try:
            if url:
                webbrowser.open(url)
                return (
                    "web_search_open_first",
                    q[:120],
                    _msg(lang, "search_open_first_ok", query=q[:80]),
                    "ok",
                )
            webbrowser.open(serp)
            return (
                "web_search",
                q[:120],
                _msg(lang, "search_open_first_fallback", query=q[:80]),
                "partial",
            )
        except Exception as e:
            return (
                "web_search_open_first",
                q[:120],
                _msg(lang, "search_fail"),
                f"error:{e}",
            )
    return None


def _try_web_search(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if re.search(r"\b(open|launch|start)\s+google\s+chrome\b", norm):
        return None
    q = _extract_search_query(norm)
    if not q:
        return None
    url = "https://www.google.com/search?q=" + quote_plus(q)
    try:
        webbrowser.open(url)
        return ("web_search", q[:120], _msg(lang, "search_ok"), "ok")
    except Exception as e:
        return ("web_search", q[:120], _msg(lang, "search_fail"), f"error:{e}")


def _try_youtube_combined(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """e.g. open youtube and play justin bieber, youtube search for cats."""
    patterns = [
        re.compile(
            r"\b(?:open\s+(?:the\s+)?)?youtube\s+(?:and\s+)?"
            r"(?:play|search(?:\s+for)?|for|watch|listen\s+to)\s+(.+)",
            re.I,
        ),
        re.compile(r"\bopen\s+youtube\s+and\s+(.+)", re.I),
    ]
    for p in patterns:
        m = p.search(norm)
        if m:
            q = m.group(1).strip()
            q = re.sub(r"\b(please|now)\s*$", "", q).strip()
            if len(q) < 1:
                return None
            if session_ops.playwright_available() and automation_implemented("youtube"):
                ok, msg = session_ops.start_youtube_session(lang)
                if ok:
                    turn = session_ops.run_session_turn(lang, f"search {q}")
                    reply = str(turn.get("reply", "")).strip() or msg
                    return ("session_youtube", q[:120], reply, "ok")
                return ("session_youtube", q[:120], msg, "fail")
            url = "https://www.youtube.com/results?search_query=" + quote_plus(q)
            try:
                webbrowser.open(url)
                return (
                    "youtube_search",
                    q[:120],
                    _msg(lang, "youtube_search_ok", query=q[:80]),
                    "ok",
                )
            except Exception as e:
                return (
                    "youtube_search",
                    q[:120],
                    _msg(lang, "site_fail"),
                    f"error:{e}",
                )
    return None


def _try_open_chatgpt_session(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\b(open|launch|start)\s+(?:the\s+)?chat\s*gpt\b", norm):
        return None
    if session_ops.playwright_available() and automation_implemented("chatgpt"):
        ok, msg = session_ops.start_chatgpt_session(lang)
        if ok:
            return ("session_chatgpt", "chatgpt", msg, "ok")
        return ("session_chatgpt", "chatgpt", msg, "fail")
    try:
        webbrowser.open("https://chatgpt.com")
        return ("open_site", "chatgpt", _msg(lang, "site_open", name="ChatGPT"), "ok")
    except Exception as e:
        return ("open_site", "chatgpt", _msg(lang, "site_fail"), f"error:{e}")


def _try_open_google_maps_session(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(
        r"\b(open|launch|start|go\s+to)\s+(?:the\s+)?google\s+maps\b",
        norm,
        re.I,
    ):
        return None
    if session_ops.playwright_available() and automation_implemented("google_maps"):
        ok, msg = session_ops.start_google_maps_session(lang)
        if ok:
            return ("session_google_maps", "google_maps", msg, "ok")
        return ("session_google_maps", "google_maps", msg, "fail")
    try:
        webbrowser.open("https://www.google.com/maps")
        return ("open_site", "google_maps", _msg(lang, "site_open", name="Google Maps"), "ok")
    except Exception as e:
        return ("open_site", "google_maps", _msg(lang, "site_fail"), f"error:{e}")


def _try_open_wikipedia_session(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\b(open|launch|start|go\s+to)\s+(?:the\s+)?wikipedia\b", norm, re.I):
        return None
    if session_ops.playwright_available() and automation_implemented("wikipedia"):
        ok, msg = session_ops.start_wikipedia_session(lang)
        if ok:
            return ("session_wikipedia", "wikipedia", msg, "ok")
        return ("session_wikipedia", "wikipedia", msg, "fail")
    try:
        webbrowser.open("https://www.wikipedia.org/")
        return ("open_site", "wikipedia", _msg(lang, "site_open", name="Wikipedia"), "ok")
    except Exception as e:
        return ("open_site", "wikipedia", _msg(lang, "site_fail"), f"error:{e}")


def _try_open_google_news_session(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(
        r"\b(open|launch|start|go\s+to)\s+(?:the\s+)?google\s+news\b",
        norm,
        re.I,
    ):
        return None
    if session_ops.playwright_available() and automation_implemented("google_news"):
        ok, msg = session_ops.start_google_news_session(lang)
        if ok:
            return ("session_google_news", "google_news", msg, "ok")
        return ("session_google_news", "google_news", msg, "fail")
    try:
        webbrowser.open(
            "https://news.google.com/home?hl=en-MY&gl=MY&ceid=MY:en",
        )
        return ("open_site", "google_news", _msg(lang, "site_open", name="Google News"), "ok")
    except Exception as e:
        return ("open_site", "google_news", _msg(lang, "site_fail"), f"error:{e}")


def _try_open_google_maps_open_keyword(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\bgoogle\s+maps\b", norm, re.I):
        return None
    if not re.search(r"\bopen\b", norm, re.I):
        return None
    if not (
        session_ops.playwright_available() and automation_implemented("google_maps")
    ):
        return None
    try:
        ok, msg = session_ops.start_google_maps_session(lang)
        if ok:
            return ("session_google_maps", "google_maps", msg, "ok")
        return ("session_google_maps", "google_maps", msg, "fail")
    except Exception as e:
        return ("session_google_maps", "google_maps", str(e), "fail")


def _try_open_wikipedia_open_keyword(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\bwikipedia\b", norm, re.I):
        return None
    if not re.search(r"\bopen\b", norm, re.I):
        return None
    if not (
        session_ops.playwright_available() and automation_implemented("wikipedia")
    ):
        return None
    try:
        ok, msg = session_ops.start_wikipedia_session(lang)
        if ok:
            return ("session_wikipedia", "wikipedia", msg, "ok")
        return ("session_wikipedia", "wikipedia", msg, "fail")
    except Exception as e:
        return ("session_wikipedia", "wikipedia", str(e), "fail")


def _try_open_google_news_open_keyword(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\b(google\s+news|googlenews)\b", norm, re.I):
        return None
    if not re.search(r"\bopen\b", norm, re.I):
        return None
    if not (session_ops.playwright_available() and automation_implemented("google_news")):
        return None
    try:
        ok, msg = session_ops.start_google_news_session(lang)
        if ok:
            return ("session_google_news", "google_news", msg, "ok")
        return ("session_google_news", "google_news", msg, "fail")
    except Exception as e:
        return ("session_google_news", "google_news", str(e), "fail")


def _try_open_whatsapp_session(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\b(open|launch|start)\s+(?:the\s+)?whatsapp\b", norm):
        return None
    ok, msg = session_ops.start_whatsapp_session(lang)
    if ok:
        return ("session_whatsapp", "whatsapp", msg, "ok")
    return ("session_whatsapp", "whatsapp", msg, "fail")


def _try_open_youtube_open_keyword(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Word match: both ``open`` and ``youtube`` anywhere (e.g. ``youtube open``, ``please open youtube now``).
    ``search the web and open for youtube`` is handled earlier by ``_try_web_search_open_first``.
    """
    if not re.search(r"\byoutube\b", norm, re.I):
        return None
    if not re.search(r"\bopen\b", norm, re.I):
        return None
    if not (
        session_ops.playwright_available() and automation_implemented("youtube")
    ):
        return None
    try:
        ok, msg = session_ops.start_youtube_session(lang)
        if ok:
            return ("session_youtube", "youtube", msg, "ok")
        return ("session_youtube", "youtube", msg, "fail")
    except Exception as e:
        return ("session_youtube", "youtube", str(e), "fail")


def _try_open_site(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if "google chrome" in norm:
        return None
    m = re.search(
        r"\b(open|launch|go to|start)\s+(the\s+)?(youtube|google|gmail|github|outlook|"
        r"facebook|twitter|reddit|linkedin)\b",
        norm,
    )
    if not m:
        return None
    site = m.group(3)
    url = SITE_ALIASES.get(site)
    if not url:
        return None
    if site == "youtube" and session_ops.playwright_available() and automation_implemented(
        "youtube"
    ):
        ok, msg = session_ops.start_youtube_session(lang)
        if ok:
            return ("session_youtube", "youtube", msg, "ok")
    try:
        webbrowser.open(url)
        return ("open_site", site, _msg(lang, "site_open", name=site.title()), "ok")
    except Exception as e:
        return ("open_site", site, _msg(lang, "site_fail"), f"error:{e}")


def _try_open_url_explicit(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    m = re.search(r"(https?://[^\s]+)", norm)
    if not m:
        return None
    url = m.group(1).rstrip(".,);")
    if not _safe_url(url):
        return ("open_url", url, _msg(lang, "site_fail"), "bad_url")
    try:
        webbrowser.open(url)
        return ("open_url", url[:100], _msg(lang, "url_open"), "ok")
    except Exception as e:
        return ("open_url", url[:100], _msg(lang, "site_fail"), f"error:{e}")


# --- Screenshot, media keys, clipboard ---


def _try_screenshot(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if not re.search(r"\b(screenshot|screen\s*shot|capture\s+(?:the\s+)?screen)\b", norm):
        return None
    ok, note, path = _screenshot_fixed()
    if ok:
        return ("screenshot", path, _msg(lang, "screenshot_ok"), "ok")
    return ("screenshot", note, _msg(lang, "screenshot_fail"), note)


def _try_system_volume(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """Default playback master volume (+/- ``_SYSTEM_VOLUME_STEP_PCT``). Phrases must include
    the word *system* (e.g. ``increase system volume``) so they do not collide with
    YouTube in-session volume shortcuts.
    """
    n = (norm or "").strip().lower()
    if not n:
        return None
    step = _SYSTEM_VOLUME_STEP_PCT
    vol_up = re.search(
        r"\b(increase|raise|turn\s+up)\s+(?:the\s+)?system\s+volume\b|\b"
        r"system\s+volume\s+(?:up|higher|louder)(?:\s+please)?\b",
        n,
    )
    vol_down = re.search(
        r"\b(decrease|lower|turn\s+down)\s+(?:the\s+)?system\s+volume\b|\b"
        r"system\s+volume\s+(?:down|lower|quieter)(?:\s+please)?\b",
        n,
    )
    if vol_up:
        ok, note = _adjust_master_volume_percent(step)
        if ok:
            return ("volume_up", "", _msg(lang, "volume_up_ok"), "ok")
        return ("volume_up", note, _msg(lang, "volume_adjust_fail"), note)
    if vol_down:
        ok, note = _adjust_master_volume_percent(-step)
        if ok:
            return ("volume_down", "", _msg(lang, "volume_down_ok"), "ok")
        return ("volume_down", note, _msg(lang, "volume_adjust_fail"), note)
    return None


def _try_media(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    matched = re.search(
        r"\b(pause\s+(?:the\s+)?(?:video|youtube|music)|play\s+(?:the\s+)?(?:video|youtube|music)|"
        r"resume\s+(?:the\s+)?(?:video|music)|toggle\s+play|play\s+pause|"
        r"youtube\s+(pause|play))\b",
        norm,
    )
    if not matched and not (
        re.search(r"\b(pause|play|resume)\b", norm)
        and re.search(r"\b(video|youtube|music|song|spotify)\b", norm)
    ):
        return None
    ok, note = _media_play_pause()
    if ok:
        return ("media_play_pause", "", _msg(lang, "media_ok"), "ok")
    return ("media_play_pause", note, _msg(lang, "media_fail"), note)


def _try_clipboard(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    if re.search(r"\b(copy\s+(?:that|this|it|selection|text)?|copy\s*$)\b", norm) and "copyright" not in norm:
        ok, note = _clipboard_shortcut("c")
        if ok:
            return ("clipboard_copy", "", _msg(lang, "copy_ok"), "ok")
        return ("clipboard_copy", note, _msg(lang, "clipboard_fail"), note)
    if re.search(r"\b(paste\s+(?:that|this|it)?|paste\s*$)\b", norm):
        ok, note = _clipboard_shortcut("v")
        if ok:
            return ("clipboard_paste", "", _msg(lang, "paste_ok"), "ok")
        return ("clipboard_paste", note, _msg(lang, "clipboard_fail"), note)
    return None


# --- User folders, applications, and explicit file paths ---


def _try_open_folder(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    m = re.search(
        r"\b(open|show)\s+(?:my\s+)?(downloads|documents|desktop|pictures|music|videos)\b",
        norm,
    )
    if not m:
        return None
    name = m.group(2)
    sub = FOLDER_ALIASES.get(name)
    if not sub:
        return None
    target = Path.home() / sub
    ok, note = _open_path_safe(target)
    if ok:
        return ("open_folder", str(target), _msg(lang, "folder_open", name=name), "ok")
    return ("open_folder", str(target), _msg(lang, "folder_fail"), note)


def _try_open_app(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    m = re.search(
        r"\b(open|launch|start)\s+(?:the\s+|my\s+)?([\w\s]+?)(?:\s+please)?\s*$",
        norm,
    )
    if not m:
        return None
    raw = m.group(2).strip()
    if raw.startswith("google chrome") or raw == "google chrome":
        phrase = "google chrome"
        ok, note = _launch_app(phrase)
        if ok:
            return ("open_app", phrase, _msg(lang, "app_open", name="Google Chrome"), "ok")
        return ("open_app", phrase, _msg(lang, "app_fail"), note)
    # Avoid eating "youtube" here (handled by site / youtube_search)
    for site in SITE_ALIASES:
        if raw == site or raw.startswith(site + " "):
            return None
    sorted_keys = sorted(APP_ALIASES.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if raw == key or raw.startswith(key + " "):
            ok, note = _launch_app(key)
            if ok:
                return ("open_app", key, _msg(lang, "app_open", name=key.title()), "ok")
            return ("open_app", key, _msg(lang, "app_fail"), note)
    token = raw.split()[0] if raw else ""
    for length in (3, 2, 1):
        parts = raw.split()
        if len(parts) >= length:
            phrase = " ".join(parts[:length])
            if phrase in APP_ALIASES:
                ok, note = _launch_app(phrase)
                if ok:
                    return ("open_app", phrase, _msg(lang, "app_open", name=phrase.title()), "ok")
                return ("open_app", phrase, _msg(lang, "app_fail"), note)
    if token in APP_ALIASES:
        ok, note = _launch_app(token)
        if ok:
            return ("open_app", token, _msg(lang, "app_open", name=token.title()), "ok")
        return ("open_app", token, _msg(lang, "app_fail"), note)
    return None


def _resolve_pending_confirmation(
    norm: str, lang: str
) -> Optional[Tuple[str, str, str, str]]:
    """Handle yes/no after ``clarify``; clear pending and fall through if user says something else."""
    global _PENDING_CONFIRM
    if not _PENDING_CONFIRM:
        return None
    yn = _parse_yes_no(norm)
    if yn is None:
        _PENDING_CONFIRM = None
        return None
    if yn is False:
        _PENDING_CONFIRM = None
        return ("clarify_cancel", "", _msg(lang, "clarify_cancel"), "ok")
    if _PENDING_CONFIRM.get("type") == "open_app":
        key = _PENDING_CONFIRM["key"]
        _PENDING_CONFIRM = None
        ok, note = _launch_app(key)
        if ok:
            return ("open_app", key, _msg(lang, "app_open", name=key.title()), "ok")
        return ("open_app", key, _msg(lang, "app_fail"), note)
    _PENDING_CONFIRM = None
    return None


def pending_system_confirmation() -> bool:
    """True while waiting for yes/no after a fuzzy app match (router should still use system)."""
    return _PENDING_CONFIRM is not None


def _try_fuzzy_open_confirm(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    """If open X is unknown, ask to confirm best fuzzy match to a known app alias."""
    global _PENDING_CONFIRM
    m = re.search(
        r"\b(?:open|launch|start)\s+(?:the\s+|my\s+)?(.+?)(?:\s+please)?\s*$",
        norm,
    )
    if not m:
        return None
    raw = m.group(1).strip().lower()
    raw = re.sub(r"^(a|an|the)\s+", "", raw).strip()
    if not raw or len(raw) < 2:
        return None
    for site in SITE_ALIASES:
        if raw == site or raw.startswith(site + " "):
            return None
    keys = sorted(APP_ALIASES.keys(), key=len, reverse=True)
    matches = difflib.get_close_matches(raw, keys, n=1, cutoff=0.55)
    if not matches:
        return None
    best = matches[0]
    if raw == best:
        return None
    ratio = difflib.SequenceMatcher(a=raw, b=best).ratio()
    if ratio < 0.55:
        return None
    display = best.title()
    _PENDING_CONFIRM = {"type": "open_app", "key": best, "display": display}
    return ("clarify_open_app", best, _msg(lang, "clarify_open", name=display), "clarify")


def _try_open_file_path(norm: str, lang: str) -> Optional[Tuple[str, str, str, str]]:
    m = re.search(r"\bopen\s+(?:file\s+)?(?:path\s+)?([a-z]:\\[^\n]+|~[/\\][^\n]+)", norm, re.I)
    if not m:
        return None
    raw = m.group(1).strip().rstrip(".,)")
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return ("open_file", raw, _msg(lang, "bad_path"), "resolve_error")
    ok, note = _open_path_safe(p)
    if ok:
        return ("open_file", str(p), _msg(lang, "folder_open", name="file"), "ok")
    return ("open_file", str(p), _msg(lang, "bad_path"), note)


# =============================================================================
# Dispatcher: runs handlers in fixed priority order until one matches
# =============================================================================


def _dispatch(norm: str, lang: str) -> Tuple[str, str, str, str]:
    resolved = _resolve_pending_confirmation(norm, lang)
    if resolved is not None:
        return resolved
    chain: List[Callable[[str, str], Optional[Tuple[str, str, str, str]]]] = [
        _try_timer,
        _try_alarm,
        _try_time_date,
        _try_open_url_explicit,
        _try_open_chatgpt_session,
        _try_open_google_maps_session,
        _try_open_wikipedia_session,
        _try_open_google_news_session,
        _try_open_whatsapp_session,
        _try_web_search_open_first,
        _try_web_search,
        _try_youtube_combined,
        _try_open_youtube_open_keyword,
        _try_open_google_maps_open_keyword,
        _try_open_wikipedia_open_keyword,
        _try_open_google_news_open_keyword,
        _try_open_site,
        _try_screenshot,
        _try_system_volume,
        _try_clipboard,
        _try_open_folder,
        _try_open_file_path,
        _try_open_app,
        _try_fuzzy_open_confirm,
        _try_media,
    ]
    for fn in chain:
        out = fn(norm, lang)
        if out is not None:
            return out
    return ("none", "", _msg(lang, "no_intent"), "no_match")


# =============================================================================
# Append one row to system_layer_results.csv
# =============================================================================


def _append_result_row(
    ts: str,
    voice_language: str,
    input_text: str,
    intent: str,
    detail: str,
    reply: str,
    latency_s: float,
    status: str,
    note: str,
) -> None:
    new_file = (not RESULT_CSV.is_file()) or RESULT_CSV.stat().st_size == 0
    with RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(CSV_HEADER)
        w.writerow(
            [
                ts,
                voice_language,
                input_text[:500],
                intent,
                detail[:300],
                reply[:300],
                f"{latency_s:.6f}",
                status,
                note[:500],
            ]
        )


def _next_evaluation_id() -> int:
    global _EVAL_NEXT_ID
    if _EVAL_NEXT_ID is not None:
        out = _EVAL_NEXT_ID
        _EVAL_NEXT_ID += 1
        return out

    if (not EVAL_RESULT_CSV.is_file()) or EVAL_RESULT_CSV.stat().st_size == 0:
        _EVAL_NEXT_ID = 2
        return 1

    last_id = 0
    try:
        with EVAL_RESULT_CSV.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    last_id = max(last_id, int((row.get("id") or "0").strip()))
                except (TypeError, ValueError):
                    continue
    except OSError:
        last_id = 0

    _EVAL_NEXT_ID = last_id + 2
    return last_id + 1


def _append_evaluation_row(
    voice_language: str,
    message: str,
    latency_s: float,
    status: str,
) -> None:
    new_file = (not EVAL_RESULT_CSV.is_file()) or EVAL_RESULT_CSV.stat().st_size == 0
    with EVAL_RESULT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(EVAL_CSV_HEADER)
        w.writerow(
            [
                _next_evaluation_id(),
                voice_language,
                message[:500],
                f"{latency_s:.6f}",
                "TRUE" if status == "ok" else "FALSE",
            ]
        )


# =============================================================================
# Public API: entry point from main.py
# =============================================================================


def run_system(voice_language: str, text: str, source_text: str = "") -> Dict[str, object]:
    """
    Parse English command text, run one safe OS action, return reply for TTS.

    voice_language: 'en' | 'zh' — controls spoken message language only.
    """
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    text = (text or "").strip()
    source_text = (source_text or "").strip()
    lang = voice_language if voice_language in ("en", "zh") else "en"
    if lang == "zh" and source_text:
        mapped = canonicalize_zh_system_command(source_text)
        if mapped:
            text = mapped

    if not text:
        reply = _msg(voice_language if voice_language in ("en", "zh") else "en", "no_intent")
        latency_s = time.perf_counter() - t0
        _append_result_row(ts, voice_language, "", "none", "", reply, latency_s, "empty", "")
        _append_evaluation_row(voice_language, "", latency_s, "empty")
        return {
            "reply": reply,
            "latency_s": latency_s,
            "intent": "none",
            "detail": "",
            "status": "empty",
        }

    norm = _normalize(text)

    if session_ops.session_active():
        # If zh canonicalization produced ``search the web for X``, session parsers
        # treat the whole tail as the query. In automation sessions, bare ``search X``
        # is the intended meaning — strip the web-search prefix.
        t_sess = (text or "").strip()
        t_sess = re.sub(
            r"(?i)^search\s+the\s+web\s+for\s+",
            "search ",
            t_sess,
        ).strip()
        sess_out = session_ops.run_session_turn(
            voice_language,
            t_sess,
            source_text=source_text,
        )
        reply = str(sess_out["reply"])
        latency_s = float(sess_out["latency_s"])
        intent = str(sess_out.get("intent", "session"))
        detail = str(sess_out.get("detail", ""))
        status = str(sess_out.get("status", "ok"))
        note = "session_mode" if status != "no_match" else "session_no_match"
        _append_result_row(ts, voice_language, t_sess, intent, detail, reply, latency_s, status, note)
        _append_evaluation_row(voice_language, t_sess, latency_s, status)
        return {
            "reply": reply,
            "latency_s": latency_s,
            "intent": intent,
            "detail": detail,
            "status": status,
            "session_mode": True,
        }

    intent, detail, reply, status = _dispatch(norm, lang)

    latency_s = time.perf_counter() - t0
    note = "" if status == "ok" else status
    logged_input = source_text if (lang == "zh" and source_text) else text
    _append_result_row(ts, voice_language, logged_input, intent, detail, reply, latency_s, status, note)
    _append_evaluation_row(voice_language, logged_input, latency_s, status)

    return {
        "reply": reply,
        "latency_s": latency_s,
        "intent": intent,
        "detail": detail,
        "status": status,
    }


# =============================================================================
# Manual test when running this file directly
# =============================================================================

if __name__ == "__main__":
    print("=== System layer ===")
    s = input("Command text: ").strip() or "open youtube"
    out = run_system("en", s)
    print(out)
