"""
Run all Playwright sync API work on one dedicated thread.

FastAPI voice rounds use ``asyncio.to_thread``, so each round may run on a different
worker thread. Playwright's sync driver binds to the greenlet that created the
connection; cross-thread calls raise "Cannot switch to a different thread" and surface
as session 操作失败 even when parsing succeeded (e.g. ``search 沙巴`` → ``search 沙巴``).
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, TypeVar

_T = TypeVar("_T")

_init_lock = threading.Lock()
_request_queue: queue.Queue | None = None
_worker_thread: threading.Thread | None = None
_worker_thread_id: int | None = None


def _worker_loop() -> None:
    global _worker_thread_id
    _worker_thread_id = threading.get_ident()
    assert _request_queue is not None
    while True:
        item = _request_queue.get()
        if item is None:
            break
        fn, result_q = item
        try:
            result_q.put((True, fn()))
        except BaseException as exc:
            result_q.put((False, exc))


def _ensure_worker() -> None:
    global _request_queue, _worker_thread
    with _init_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _request_queue = queue.Queue()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="playwright-automation",
            daemon=True,
        )
        _worker_thread.start()


def run_on_playwright_thread(fn: Callable[[], _T]) -> _T:
    """Execute ``fn`` on the Playwright worker thread; block until done."""
    if _worker_thread_id is not None and threading.get_ident() == _worker_thread_id:
        return fn()
    _ensure_worker()
    assert _request_queue is not None
    result_q: queue.Queue = queue.Queue(maxsize=1)
    _request_queue.put((fn, result_q))
    ok, payload = result_q.get()
    if ok:
        return payload
    raise payload
