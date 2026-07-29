"""
Continuous automation session: YouTube / ChatGPT via Playwright CDP (attached Edge),
or WhatsApp desktop (no browser).

Requires Edge running with remote debugging before starting YouTube/ChatGPT automation.
See System/browser_control.py and System/Automation/__init__.py.

Stop with: "stop automation", "stop operation", "end session", etc.
"""

from __future__ import annotations

# =============================================================================
# Imports
# =============================================================================

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Pattern, Tuple

import subprocess

from .browser_control import PlaywrightBrowser, media_play_pause
from .playwright_executor import run_on_playwright_thread
from .Automation.whatsapp_desktop import (
    clear_search as whatsapp_clear_search,
    clear_message as whatsapp_clear_message,
    open_whatsapp_desktop,
    search_chat as whatsapp_search_chat,
    select_chat_index as whatsapp_select_chat_index,
    send_message as whatsapp_send_message,
    type_message as whatsapp_type_message,
)

# =============================================================================
# Session timeout, globals, and synchronization primitives
# =============================================================================

# End session (and close Chromium) after this many seconds with no speech / activity refresh
SESSION_IDLE_TIMEOUT_SEC = 3600

_last_activity_ts: float = 0.0
_idle_stop_event: Optional[threading.Event] = None
_idle_thread: Optional[threading.Thread] = None
_idle_timeout_message: Optional[str] = None
_session_lock = threading.Lock()

# =============================================================================
# Text normalization and command pattern tables
# =============================================================================

# Flexible normalization: fillers + light synonyms (extend as needed)
_FILLER_RE = re.compile(
    r"\b(please|can you|could you|would you|just|for me|now)\b",
    re.I,
)


def normalize_flexible(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = _FILLER_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # common equivalences
    t = re.sub(r"\bresume\b", "resume", t)
    t = re.sub(r"\bunpause\b", "resume", t)
    return t


def _compact_zh(text: str) -> str:
    """Remove spaces/punctuation for Chinese command matching (session layer only)."""
    t = (text or "").strip().lower()
    t = re.sub(r"[，。！？、；：“”\"'（）()【】\[\],.!?;:]", "", t)
    return re.sub(r"\s+", "", t)


# (regex, action_id, group_for_slot or None) — first match wins; order matters (specific first)
# Wikipedia / Google Maps / Google News: same voice patterns as ChatGPT (search / find / enter …).
_SITE_BROWSER_KINDS = frozenset({"wikipedia", "google_maps", "google_news"})
_PLAYWRIGHT_SESSION_KINDS = frozenset(
    {"youtube", "chatgpt", "wikipedia", "google_maps", "google_news"}
)

_ORDINAL_ALIASES = {
    "1": "first",
    "1st": "first",
    "2": "second",
    "2nd": "second",
    "3": "third",
    "3rd": "third",
}


def _normalize_chat_ordinal(val: str) -> str:
    v = (val or "").strip().lower()
    return _ORDINAL_ALIASES.get(v, v)


_SESSION_ACTIONS: List[Tuple[Pattern[str], str, Optional[str]]] = [
    (
        re.compile(
            r"^(?:select|open|choose)(?:\s+(?:the|a))?\s+(?:chat|conversation)\s+"
            r"(first|second|third|1st|2nd|3rd)$",
            re.I,
        ),
        "select_chat_index",
        "ordinal",
    ),
    (
        re.compile(
            r"^(?:select|open|choose)(?:\s+(?:the|a))?\s+"
            r"(first|second|third|1st|2nd|3rd)\s+(?:chat|conversation)$",
            re.I,
        ),
        "select_chat_index",
        "ordinal",
    ),
    (
        re.compile(
            r"^search\s+(?:chat|user)\s+(.+)$",
            re.I,
        ),
        "search_chat",
        "chat",
    ),
    (
        re.compile(
            r"^(?:search|look\s+up|find)(?:\s+for)?\s+(.+)$",
            re.I,
        ),
        "search",
        "query",
    ),
    (
        re.compile(r"^play(?:\s+the)?\s+first(?:\s+video)?$", re.I),
        "play_first",
        None,
    ),
    (
        re.compile(r"^pause(?:\s+the)?\s*video$|^pause$", re.I),
        "pause",
        None,
    ),
    (
        re.compile(r"^resume(?:\s+the)?\s*video$|^resume$|^play(?:\s+the)?\s*video$", re.I),
        "resume",
        None,
    ),
    (
        re.compile(r"^send(?:\s+the)?\s*message$|^send$|^send\s+it$", re.I),
        "send",
        None,
    ),
    (
        re.compile(
            r"^clear\s+(?:the\s+)?search(?:\s+(?:user|chat))?$",
            re.I,
        ),
        "clear_search",
        None,
    ),
    (
        re.compile(
            r"^(?:clear|delete|remove)\s+(?:the\s+)?(?:entire\s+)?message$|^clear\s+text$",
            re.I,
        ),
        "clear_message",
        None,
    ),
    (
        re.compile(r"^(?:type|write|enter)\s+(.+)$", re.I),
        "type_text",
        "text",
    ),
    (
        re.compile(r"^click(?:\s+the)?\s*first(?:\s+chat)?$|^open\s+first\s+chat$", re.I),
        "click_first_chat",
        None,
    ),
]


_STOP_RE = re.compile(
    r"\b(stop\s+(?:the\s+)?(?:operation|session|automation)|end\s+session|exit\s+session|"
    r"cancel\s+(?:operation|automation)|stop\s+assistant)\b",
    re.I,
)

# =============================================================================
# Command parsing helpers
# =============================================================================


def is_stop_command(text: str) -> bool:
    flex = normalize_flexible(text)
    return bool(_STOP_RE.search(flex) or _STOP_RE.search((text or "").lower()))


def match_youtube_session_action(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    YouTube-only: loose word-based matching.

    - search: leading search / look up / find … (+ query)
    - play_first: word ``play`` and word ``first`` anywhere
    - pause: word ``pause`` anywhere
    - resume: word ``resume`` anywhere (unpause → resume in normalize_flexible)
    """
    flex = normalize_flexible(text)
    if not flex:
        return None
    m = re.match(r"^(?:search|look\s+up|find)(?:\s+for)?\s+(.+)$", flex, re.I)
    if m:
        q = m.group(1).strip()
        if q:
            return ("search", {"query": q})
    # ``play first`` plus common ASR / translation variants:
    # ``play the first``, ``play the first one``, ``play first video``, etc.
    if re.search(
        r"\bplay(?:s|ing|ed)?\b.*\b(?:the\s+)?first(?:\s+(?:one|video))?\b",
        flex,
        re.I,
    ) or re.search(
        r"\b(?:the\s+)?first(?:\s+(?:one|video))?\b.*\bplay(?:s|ing|ed)?\b",
        flex,
        re.I,
    ):
        return ("play_first", {})
    if re.search(
        r"\b(increase|raise|turn\s+up)\s+volume\b|\bvolume\s+(up|higher)\b|\blouder\b",
        flex,
        re.I,
    ):
        return ("volume_up", {})
    if re.search(
        r"\b(decrease|lower|turn\s+down)\s+volume\b|\bvolume\s+(down|lower)\b|\bquieter\b",
        flex,
        re.I,
    ):
        return ("volume_down", {})
    if re.search(
        r"\b(?:stop|pause)\s+(?:playing|playback|the\s+video)\b",
        flex,
        re.I,
    ):
        return ("pause", {})
    if re.search(r"\bpause\b", flex):
        return ("pause", {})
    if re.search(
        r"\b(?:continue|resume)\s+(?:playing|playback|the\s+video)\b",
        flex,
        re.I,
    ):
        return ("resume", {})
    if re.search(r"\bresume\b", flex):
        return ("resume", {})
    return None


def match_youtube_chinese_session_action(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    YouTube session: Chinese phrases (``normalize_flexible`` strips CJK, so English
    regexes never match). Keep allowlist-style patterns only.
    """
    raw = (text or "").strip()
    if not raw or not re.search(r"[\u4e00-\u9fff]", raw):
        return None
    t = _compact_zh(raw)
    for p in (
        r"^(请帮我|请你帮我|麻烦你帮我|麻烦你|帮我|请你|请)",
        r"^(可以帮我|可不可以帮我|能不能帮我|能不能|可不可以|可以|能否)",
        r"(一下子?|好吗|谢谢)$",
    ):
        t = re.sub(p, "", t)

    # Search: 搜索歌 / 搜索周杰伦 / 查找歌曲xxx / 搜歌xxx
    m = re.match(r"^(?:搜索|查找)(?:歌曲|歌)?(.+)$", t)
    if m:
        q = m.group(1).strip()
        if q:
            return ("search", {"query": q})
    m = re.match(r"^搜歌(.+)$", t)
    if m:
        q = m.group(1).strip()
        if q:
            return ("search", {"query": q})
    m = re.match(r"^找(?:歌|歌曲)?(.+)$", t)
    if m:
        q = m.group(1).strip()
        if q:
            return ("search", {"query": q})

    # Play first video (e.g. ``播放第一个`` / ``播放第一个视频`` — same intent as English ``play first``)
    if re.search(r"^(?:播放|放)(?:第)?一(?:个)?(?:视频|影片)?$", t):
        return ("play_first", {})
    if re.search(r"(?:播放|放).*(?:第)?一(?:个)?(?:视频|影片)", t):
        return ("play_first", {})

    if re.search(
        r"(?:提高|增大|加大|调高)(?:一下)?音量|音量(?:加大|提高|增大|调高|调大)|大声点",
        t,
    ):
        return ("volume_up", {})
    if re.search(
        r"(?:降低|减小|调低)(?:一下)?音量|音量(?:降低|减小|调低|调小)|小声点",
        t,
    ):
        return ("volume_down", {})

    if re.search(r"暂停|停止(?:播放|音乐|视频|歌曲)|停播", t):
        return ("pause", {})
    if "音量" not in t and re.search(r"(?:继续|恢复)(?:播放|音乐|视频|歌曲)?", t):
        return ("resume", {})
    if "音量" not in t and re.fullmatch(r"播放(?:音乐|视频|歌曲)?", t):
        return ("resume", {})
    return None


def match_whatsapp_chinese_session_action(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    WhatsApp session: Chinese-first parser so command words are stripped locally
    (e.g. ``输入你好`` -> ``type_text: 你好``, ``搜索聊天Ken`` -> ``search_chat: Ken``).
    """
    raw = (text or "").strip()
    if not raw or not re.search(r"[\u4e00-\u9fff]", raw):
        return None
    t = _compact_zh(raw)
    for p in (
        r"^(请帮我|请你帮我|麻烦你帮我|麻烦你|帮我|请你|请)",
        r"^(可以帮我|可不可以帮我|能不能帮我|能不能|可不可以|可以|能否)",
        r"(一下子?|好吗|谢谢)$",
    ):
        t = re.sub(p, "", t)

    m = re.match(r"^(?:搜索|查找)(?:聊天|用户)(.+)$", t)
    if m:
        q = m.group(1).strip()
        if q:
            return ("search_chat", {"chat": q})

    m = re.search(r"(?:选择|打开)(?:第)?(?P<ord>一|二|三|1|2|3)(?:个)?(?:聊天|对话)", t)
    if m:
        ord_map = {"一": "first", "1": "first", "二": "second", "2": "second", "三": "third", "3": "third"}
        ord_word = ord_map.get(m.group("ord"), "")
        if ord_word:
            return ("select_chat_index", {"ordinal": ord_word})

    m = re.match(r"^(?:输入|写|打字)(.+)$", t)
    if m:
        body = m.group(1).strip()
        if body:
            return ("type_text", {"text": body})

    if re.fullmatch(r"(发送|送出|发出去?)", t):
        return ("send", {})
    if re.search(r"(清除|清空|删除).*(搜索|查找)", t):
        return ("clear_search", {})
    if re.search(r"(清除|清空|删除).*(消息|讯息|内容|文字)", t):
        return ("clear_message", {})
    return None


def match_chatgpt_session_action(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """
    ChatGPT-only: intent after the **first** trigger word; strip everything before
    and including that trigger (and ``search for`` / ``look up`` as a unit).

    Examples::

        help me to search what is cdp → query ``what is cdp``
        enter what is cdp → text ``what is cdp``
        please find quantum → query ``quantum``
    """
    flex = normalize_flexible(text)
    if not flex:
        return None
    # Non-greedy prefix so we bind to the *first* ``search`` / ``find`` / …, not the last.
    # Order: ``search for`` before ``search`` so ``search for x`` does not yield ``for x``.
    _CHATGPT_TRIGGERS: List[Tuple[str, str, re.Pattern[str]]] = [
        ("search", "query", re.compile(r"^(.*?)\bsearch\s+for\s+(.+)$", re.I)),
        ("search", "query", re.compile(r"^(.*?)\bsearch\s+(.+)$", re.I)),
        ("search", "query", re.compile(r"^(.*?)\blook\s+up\s+(.+)$", re.I)),
        ("search", "query", re.compile(r"^(.*?)\bfind\s+(.+)$", re.I)),
        ("type_text", "text", re.compile(r"^(.*?)\benter\s+(.+)$", re.I)),
        ("type_text", "text", re.compile(r"^(.*?)\b(?:type|write)\s+(.+)$", re.I)),
    ]
    for action_id, slot, pat in _CHATGPT_TRIGGERS:
        m = pat.match(flex)
        if m:
            val = m.group(2).strip()
            if val:
                return (action_id, {slot: val})
    return None


def match_session_action_from_text(text: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """Map flexible wording to (action_id, slots). Used for ChatGPT / WhatsApp / fallback."""
    flex = normalize_flexible(text)
    if not flex:
        return None
    for pat, action_id, slot_name in _SESSION_ACTIONS:
        m = pat.match(flex)
        if not m:
            continue
        slots: Dict[str, str] = {}
        if slot_name and m.lastindex:
            val = m.group(1).strip()
            if val:
                if slot_name == "ordinal":
                    val = _normalize_chat_ordinal(val)
                slots[slot_name] = val
        return (action_id, slots)
    return None


# =============================================================================
# Session state model
# =============================================================================

@dataclass
class SessionState:
    kind: str  # youtube | chatgpt | wikipedia | google_maps | google_news | whatsapp
    browser: Optional[PlaywrightBrowser] = None
    pending_type: str = ""  # for whatsapp: accumulate before send
    lang: str = "en"
    # WhatsApp: chat list sits one row lower while search UI is open (filters + "Chats" header).
    whatsapp_search_layout: bool = False


_SESSION: Optional[SessionState] = None

# =============================================================================
# Session lifecycle and idle watcher
# =============================================================================


def session_active() -> bool:
    return _SESSION is not None


def touch_session_activity() -> None:
    """Call after non-empty speech so the 1-hour idle timer resets."""
    global _last_activity_ts
    with _session_lock:
        if _SESSION is not None:
            _last_activity_ts = time.time()


def pop_idle_timeout_message() -> Optional[str]:
    """If idle watchdog ended the session, returns TTS text once (then None)."""
    global _idle_timeout_message
    with _session_lock:
        m = _idle_timeout_message
        _idle_timeout_message = None
        return m


def _stop_idle_watcher() -> None:
    global _idle_stop_event, _idle_thread
    if _idle_stop_event is not None:
        _idle_stop_event.set()
    _idle_stop_event = None
    _idle_thread = None


def _idle_watcher_loop() -> None:
    global _idle_timeout_message, _SESSION
    while True:
        ev = _idle_stop_event
        if ev is None:
            return
        if ev.wait(timeout=15.0):
            return
        with _session_lock:
            if _SESSION is None:
                return
            if time.time() - _last_activity_ts >= SESSION_IDLE_TIMEOUT_SEC:
                lang = _SESSION.lang
                _idle_timeout_message = _msg(lang, "session_idle_timeout")
                end_session("idle_timeout")
                return


def _start_idle_watcher() -> None:
    global _idle_stop_event, _idle_thread
    _stop_idle_watcher()
    _idle_stop_event = threading.Event()
    t = threading.Thread(target=_idle_watcher_loop, name="session_idle_watch", daemon=True)
    _idle_thread = t
    t.start()


def _close_browser(state: SessionState) -> None:
    if state.browser:
        try:
            state.browser.close()
        except Exception:
            pass
        state.browser = None


def _close_browser_unlocked() -> None:
    global _SESSION
    if _SESSION:
        _close_browser(_SESSION)


def end_session(reason: str = "stop") -> None:
    global _SESSION
    _stop_idle_watcher()

    def _clear() -> None:
        global _SESSION
        with _session_lock:
            if _SESSION:
                _close_browser(_SESSION)
            _SESSION = None

    with _session_lock:
        on_pw_thread = (
            _SESSION is not None
            and _SESSION.kind in _PLAYWRIGHT_SESSION_KINDS
            and _SESSION.browser is not None
        )
    if on_pw_thread:
        run_on_playwright_thread(_clear)
    else:
        _clear()


# =============================================================================
# User-facing response strings
# =============================================================================

def _msg(lang: str, key: str, **kwargs: Any) -> str:
    en = {
        "session_started_youtube": "Automation is running on YouTube.",
        "session_started_chatgpt": "Automation is running on ChatGPT.",
        "session_started_wikipedia": "Automation is running on Wikipedia.",
        "session_started_google_maps": "Automation is running on Google Maps.",
        "session_started_google_news": "Automation is running on Google News.",
        "session_started_whatsapp": "Automation is running on WhatsApp.",
        "session_stopped": "Session stopped.",
        "session_no_match": "I did not understand that command. Try search, play first, pause, or stop automation.",
        "session_no_match_site": "I did not understand that command. Try search, find, enter, or stop automation.",
        "session_ok_search": "Done.",
        "session_ok_search_chat": "Search updated.",
        "session_ok_play": "Playing the first video.",
        "session_ok_pause": "Paused.",
        "session_ok_resume": "Resumed.",
        "session_ok_volume_up": "Volume up.",
        "session_ok_volume_down": "Volume down.",
        "session_ok_send": "Sent.",
        "session_ok_type": "Typed.",
        "session_ok_clear_search": "Cleared the search.",
        "session_ok_clear": "Cleared the message.",
        "session_ok_click": "Selected the chat.",
        "session_fail": "That action failed. Try again or say stop automation.",
        "session_no_playwright": "Install Playwright: pip install playwright. Start Edge with remote debugging, then try again.",
        "session_idle_timeout": "Session ended: one hour with no speech. The browser was closed.",
    }
    zh = {
        "session_started_youtube": "自动化运行中在 YouTube ",
        "session_started_chatgpt": "自动化运行中在 ChatGPT ",
        "session_started_wikipedia": "自动化运行中在 维基百科 ",
        "session_started_google_maps": "自动化运行中在 谷歌地图 ",
        "session_started_google_news": "自动化运行中在 谷歌新闻 ",
        "session_started_whatsapp": "自动化运行中在 WhatsApp ",
        "session_stopped": "已结束会话。",
        "session_no_match": "未识别该指令。可尝试搜索、播放第一个、暂停，或说停止自动化。",
        "session_no_match_site": "未识别该指令。可尝试搜索、查找、输入，或说停止自动化。",
        "session_ok_search": "完成。",
        "session_ok_search_chat": "已更新搜索。",
        "session_ok_play": "正在播放第一个视频。",
        "session_ok_pause": "已暂停。",
        "session_ok_resume": "已继续播放。",
        "session_ok_volume_up": "已调高音量。",
        "session_ok_volume_down": "已调低音量。",
        "session_ok_send": "已发送。",
        "session_ok_type": "已输入。",
        "session_ok_clear_search": "已清空搜索。",
        "session_ok_clear": "已清空消息。",
        "session_ok_click": "已选择聊天。",
        "session_fail": "操作失败，请重试或说停止自动化。",
        "session_no_playwright": "请安装 Playwright：pip install playwright。请先启动带远程调试的 Edge 后再试。",
        "session_idle_timeout": "已结束会话：一小时未检测到语音，浏览器已关闭。",
    }
    d = zh if lang == "zh" else en
    return (d.get(key) or en[key]).format(**kwargs)


_NO_MATCH_SPEECH = {
    "en": "I did not understand, please try the following commands.",
    "zh": "我不明白，请尝试以下命令。",
}

_NO_MATCH_HELP_EN = {
    "whatsapp": """I did not understand, please try the following commands:
- Search user James
- Select first/second/third chat
- Enter Good Morning
- Clear Message
- Stop Automation""",
    "youtube": """I did not understand, please try the following commands:
- Search Justin Bieber
- Play First
- Pause / Resume Video
- Increase / Decrease volume
- Stop Automation""",
    "chatgpt": """I did not understand, please try the following commands:
- Enter What is Computer
- Send Message
- Search 3 + 3
- Stop Automation""",
    "site": """I did not understand, please try the following commands:
- Search United States
- Search News in Malaysia
- Stop Automation""",
}

_NO_MATCH_HELP_ZH = {
    "whatsapp": """我不明白，请尝试以下命令：
- 搜索用户小明
- 选择第一/第二/第三个聊天
- 输入早上好
- 清空消息
- 停止自动化""",
    "youtube": """我不明白，请尝试以下命令：
- 搜索周杰伦
- 播放第一个
- 暂停音乐 / 继续播放
- 调高/调低音量
- 停止自动化""",
    "chatgpt": """我不明白，请尝试以下命令：
- 搜索什么是电脑
- 发送
- 输入 3 + 3
- 停止自动化""",
    "site": """我不明白，请尝试以下命令：
- 搜索美国
- 搜索马来西亚新闻
- 停止自动化""",
}


def session_no_match_speech(lang: str) -> str:
    return _NO_MATCH_SPEECH["zh" if lang == "zh" else "en"]


def _session_help_key(kind: Optional[str]) -> str:
    if kind in _SITE_BROWSER_KINDS:
        return "site"
    if kind in {"whatsapp", "youtube", "chatgpt"}:
        return kind
    return "youtube"


def session_no_match_reply(lang: str, kind: Optional[str]) -> str:
    help_map = _NO_MATCH_HELP_ZH if lang == "zh" else _NO_MATCH_HELP_EN
    return help_map[_session_help_key(kind)]


def is_session_no_match_reply(reply: str) -> bool:
    text = (reply or "").strip()
    return any(text == value for value in (*_NO_MATCH_HELP_EN.values(), *_NO_MATCH_HELP_ZH.values()))


# =============================================================================
# Capability checks and session starters
# =============================================================================

def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def start_youtube_session(lang: str) -> Tuple[bool, str]:
    return run_on_playwright_thread(lambda: _start_youtube_session_impl(lang))


def _start_youtube_session_impl(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    if not playwright_available():
        return False, _msg(lang, "session_no_playwright")
    try:
        b = PlaywrightBrowser()
        b.youtube_home()
        _SESSION = SessionState(kind="youtube", browser=b, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_youtube")
    except Exception as e:
        return False, str(e)


def start_chatgpt_session(lang: str) -> Tuple[bool, str]:
    return run_on_playwright_thread(lambda: _start_chatgpt_session_impl(lang))


def _start_chatgpt_session_impl(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    if not playwright_available():
        return False, _msg(lang, "session_no_playwright")
    try:
        b = PlaywrightBrowser()
        b.chatgpt_open()
        _SESSION = SessionState(kind="chatgpt", browser=b, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_chatgpt")
    except Exception as e:
        return False, str(e)


def start_wikipedia_session(lang: str) -> Tuple[bool, str]:
    return run_on_playwright_thread(lambda: _start_wikipedia_session_impl(lang))


def _start_wikipedia_session_impl(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    if not playwright_available():
        return False, _msg(lang, "session_no_playwright")
    try:
        b = PlaywrightBrowser()
        b.wikipedia_open()
        _SESSION = SessionState(kind="wikipedia", browser=b, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_wikipedia")
    except Exception as e:
        return False, str(e)


def start_google_maps_session(lang: str) -> Tuple[bool, str]:
    return run_on_playwright_thread(lambda: _start_google_maps_session_impl(lang))


def _start_google_maps_session_impl(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    if not playwright_available():
        return False, _msg(lang, "session_no_playwright")
    try:
        b = PlaywrightBrowser()
        b.google_maps_open()
        _SESSION = SessionState(kind="google_maps", browser=b, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_google_maps")
    except Exception as e:
        return False, str(e)


def start_google_news_session(lang: str) -> Tuple[bool, str]:
    return run_on_playwright_thread(lambda: _start_google_news_session_impl(lang))


def _start_google_news_session_impl(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    if not playwright_available():
        return False, _msg(lang, "session_no_playwright")
    try:
        b = PlaywrightBrowser()
        b.google_news_open()
        _SESSION = SessionState(kind="google_news", browser=b, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_google_news")
    except Exception as e:
        return False, str(e)


def start_whatsapp_session(lang: str) -> Tuple[bool, str]:
    global _SESSION, _last_activity_ts
    end_session("session_replace")
    try:
        ok, note = open_whatsapp_desktop()
        if not ok:
            return False, note
        _SESSION = SessionState(kind="whatsapp", browser=None, lang=lang)
        _last_activity_ts = time.time()
        _start_idle_watcher()
        return True, _msg(lang, "session_started_whatsapp")
    except Exception as e:
        return False, str(e)


def subprocess_whatsapp() -> None:
    try:
        subprocess.Popen(
            [
                "explorer.exe",
                "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
            ],
            cwd=os.environ.get("SystemRoot", r"C:\Windows"),
        )
    except OSError:
        pass


# =============================================================================
# Main session turn dispatcher (entry used by system_layer)
# =============================================================================

def run_session_turn(
    voice_language: str, text: str, source_text: str = ""
) -> Dict[str, object]:
    """Handle one voice line while ``session_active()``."""
    with _session_lock:
        kind = _SESSION.kind if _SESSION else None
    if kind in _PLAYWRIGHT_SESSION_KINDS:
        return run_on_playwright_thread(
            lambda: _run_session_turn_impl(voice_language, text, source_text)
        )
    return _run_session_turn_impl(voice_language, text, source_text)


def _run_session_turn_impl(
    voice_language: str, text: str, source_text: str = ""
) -> Dict[str, object]:
    """Session turn implementation (Playwright sessions run via ``run_on_playwright_thread``)."""
    t0 = time.perf_counter()
    lang = voice_language if voice_language in ("en", "zh") else "en"
    global _SESSION
    if not _SESSION:
        return {
            "reply": _msg(lang, "session_stopped"),
            "latency_s": time.perf_counter() - t0,
            "intent": "session_none",
            "detail": "",
            "status": "ok",
        }

    if is_stop_command(text):
        end_session("user_stop")
        reply = _msg(lang, "session_stopped")
        lat = time.perf_counter() - t0
        return {
            "reply": reply,
            "latency_s": lat,
            "intent": "session_stop",
            "detail": "",
            "status": "ok",
        }

    state = _SESSION
    if state.kind == "youtube":
        parsed = match_youtube_chinese_session_action(source_text)
        if not parsed:
            parsed = match_youtube_chinese_session_action(text)
        if not parsed:
            parsed = match_youtube_session_action(text)
        if not parsed:
            parsed = match_session_action_from_text(text)
    elif state.kind == "chatgpt":
        parsed = match_chatgpt_session_action(text)
        if not parsed:
            parsed = match_session_action_from_text(text)
    elif state.kind in _SITE_BROWSER_KINDS:
        parsed = match_chatgpt_session_action(text)
        if not parsed:
            parsed = match_session_action_from_text(text)
    elif state.kind == "whatsapp":
        parsed = match_whatsapp_chinese_session_action(source_text)
        if not parsed:
            parsed = match_whatsapp_chinese_session_action(text)
        if not parsed:
            parsed = match_session_action_from_text(text)
    else:
        parsed = match_session_action_from_text(text)
    if not parsed:
        reply = session_no_match_reply(lang, state.kind)
        lat = time.perf_counter() - t0
        return {
            "reply": reply,
            "latency_s": lat,
            "intent": "session_unparsed",
            "detail": (text or "")[:200],
            "status": "no_match",
        }

    action_id, slots = parsed
    br = state.browser

    try:
        if state.kind == "youtube":
            out = _dispatch_youtube(
                lang, action_id, slots, br, source_text=source_text, command_text=text
            )
        elif state.kind == "chatgpt":
            out = _dispatch_chatgpt(lang, action_id, slots, br)
        elif state.kind in _SITE_BROWSER_KINDS:
            out = _dispatch_site_browser(lang, action_id, slots, br, state.kind)
        elif state.kind == "whatsapp":
            out = _dispatch_whatsapp(lang, action_id, slots)
        else:
            out = (_msg(lang, "session_fail"), "unknown_kind")
    except Exception as e:
        out = (_msg(lang, "session_fail"), str(e))

    reply, detail = out[0], out[1] if len(out) > 1 else ""
    lat = time.perf_counter() - t0
    return {
        "reply": reply,
        "latency_s": lat,
        "intent": f"session_{action_id}",
        "detail": str(detail),
        "status": "ok",
    }


# =============================================================================
# Per-site action dispatchers
# =============================================================================

def _youtube_pause_reply(lang: str, source_text: str, command_text: str) -> str:
    if lang == "zh":
        blob = _compact_zh(source_text) + _compact_zh(command_text)
        if re.search(r"停止(?:播放|音乐|视频|歌曲)|停播", blob):
            return "已停止播放。"
    return _msg(lang, "session_ok_pause")


def _dispatch_youtube(
    lang: str,
    action_id: str,
    slots: Dict[str, str],
    br: Optional[PlaywrightBrowser],
    *,
    source_text: str = "",
    command_text: str = "",
) -> Tuple[str, str]:
    if not br:
        return _msg(lang, "session_fail"), "no_browser"
    if action_id == "search":
        q = slots.get("query", "").strip()
        if not q:
            return session_no_match_reply(lang, "youtube"), ""
        ok, note = br.youtube_search(q)
        return (_msg(lang, "session_ok_search") if ok else _msg(lang, "session_fail"), note)
    if action_id == "play_first":
        ok, note = br.youtube_play_first_video()
        return (_msg(lang, "session_ok_play") if ok else _msg(lang, "session_fail"), note)
    if action_id in ("pause", "resume"):
        try:
            page = getattr(br, "page", None) if br else None
            if page is not None:
                from .Automation.focus import focus_automation_page

                focus_automation_page(page)
        except Exception:
            pass
        ok, note = media_play_pause()
        if not ok:
            return _msg(lang, "session_fail"), note
        if action_id == "pause":
            return _youtube_pause_reply(lang, source_text, command_text), note
        return _msg(lang, "session_ok_resume"), note
    if action_id == "volume_up":
        ok, note = br.youtube_volume_step(1)
        return (
            _msg(lang, "session_ok_volume_up") if ok else _msg(lang, "session_fail"),
            note,
        )
    if action_id == "volume_down":
        ok, note = br.youtube_volume_step(-1)
        return (
            _msg(lang, "session_ok_volume_down") if ok else _msg(lang, "session_fail"),
            note,
        )
    if action_id == "send":
        return session_no_match_reply(lang, "youtube"), ""
    return session_no_match_reply(lang, "youtube"), ""


def _dispatch_site_browser(
    lang: str,
    action_id: str,
    slots: Dict[str, str],
    br: Optional[PlaywrightBrowser],
    kind: str,
) -> Tuple[str, str]:
    if not br:
        return _msg(lang, "session_fail"), "no_browser"
    if action_id == "send":
        return session_no_match_reply(lang, kind), ""
    q = ""
    if action_id == "search":
        q = slots.get("query", "").strip()
    elif action_id == "type_text":
        q = slots.get("text", "").strip()
    else:
        return session_no_match_reply(lang, kind), ""
    if not q:
        return session_no_match_reply(lang, kind), ""
    if kind == "wikipedia":
        ok, note = br.wikipedia_search(q)
    elif kind == "google_maps":
        ok, note = br.google_maps_search(q)
    elif kind == "google_news":
        ok, note = br.google_news_search(q)
    else:
        return _msg(lang, "session_fail"), "unknown_kind"
    return (
        (_msg(lang, "session_ok_search") if ok else _msg(lang, "session_fail")),
        note,
    )


def _dispatch_chatgpt(
    lang: str, action_id: str, slots: Dict[str, str], br: Optional[PlaywrightBrowser]
) -> Tuple[str, str]:
    if not br:
        return _msg(lang, "session_fail"), "no_browser"
    if action_id == "type_text":
        txt = slots.get("text", "").strip()
        if not txt:
            return session_no_match_reply(lang, "chatgpt"), ""
        state = _SESSION
        if state:
            state.pending_type = txt
        return _msg(lang, "session_ok_type"), txt
    if action_id == "send":
        state = _SESSION
        body = (state.pending_type if state else "") or ""
        if not body.strip():
            ok, note = br.chatgpt_send_only()
            return (_msg(lang, "session_ok_send") if ok else _msg(lang, "session_fail"), note)
        ok, note = br.chatgpt_type_and_send(body)
        if state:
            state.pending_type = ""
        return (_msg(lang, "session_ok_send") if ok else _msg(lang, "session_fail"), note)
    if action_id == "search":
        q = slots.get("query", "").strip()
        if not q:
            return session_no_match_reply(lang, "chatgpt"), ""
        ok, note = br.chatgpt_type_and_send(q)
        return (_msg(lang, "session_ok_send") if ok else _msg(lang, "session_fail"), note)
    return session_no_match_reply(lang, "chatgpt"), ""


def _dispatch_whatsapp(lang: str, action_id: str, slots: Dict[str, str]) -> Tuple[str, str]:
    if action_id == "select_chat_index":
        ord_word = _normalize_chat_ordinal(slots.get("ordinal", ""))
        index = (
            1
            if ord_word == "first"
            else 2
            if ord_word == "second"
            else 3
            if ord_word == "third"
            else 0
        )
        if index <= 0:
            return session_no_match_reply(lang, "whatsapp"), ""
        state = _SESSION
        search_layout = bool(state.whatsapp_search_layout) if state else False
        ok, note = whatsapp_select_chat_index(index, search_layout=search_layout)
        return (_msg(lang, "session_ok_click") if ok else _msg(lang, "session_fail"), note)
    if action_id == "search_chat":
        chat = slots.get("chat", "").strip()
        if not chat:
            return session_no_match_reply(lang, "whatsapp"), ""
        ok, note = whatsapp_search_chat(chat)
        if ok and _SESSION:
            _SESSION.whatsapp_search_layout = True
        return (
            _msg(lang, "session_ok_search_chat") if ok else _msg(lang, "session_fail"),
            note,
        )
    if action_id == "click_first_chat":
        return session_no_match_reply(lang, "whatsapp"), "unsupported_click_first_chat"
    if action_id == "type_text":
        txt = slots.get("text", "").strip()
        if not txt:
            return session_no_match_reply(lang, "whatsapp"), ""
        state = _SESSION
        if state:
            state.pending_type = txt
        ok, note = whatsapp_type_message(txt)
        return (_msg(lang, "session_ok_type") if ok else _msg(lang, "session_fail"), note)
    if action_id == "send":
        ok, note = whatsapp_send_message()
        if ok and _SESSION:
            _SESSION.pending_type = ""
        return (_msg(lang, "session_ok_send") if ok else _msg(lang, "session_fail"), note)
    if action_id == "clear_search":
        ok, note = whatsapp_clear_search()
        if ok and _SESSION:
            _SESSION.whatsapp_search_layout = False
        return (_msg(lang, "session_ok_clear_search") if ok else _msg(lang, "session_fail"), note)
    if action_id == "clear_message":
        ok, note = whatsapp_clear_message()
        if ok and _SESSION:
            _SESSION.pending_type = ""
        return (_msg(lang, "session_ok_clear") if ok else _msg(lang, "session_fail"), note)
    return session_no_match_reply(lang, "whatsapp"), ""
