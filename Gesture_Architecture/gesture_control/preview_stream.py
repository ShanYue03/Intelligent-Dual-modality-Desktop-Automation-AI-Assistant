"""Background JPEG encoder for UI preview — keeps the gesture loop responsive."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

import cv2


class PreviewStream:
    """Drop-old queue + worker thread; never blocks the gesture capture loop."""

    def __init__(
        self,
        on_encoded: Callable[[bytes], None],
        *,
        max_fps: float = 18.0,
        target_width: int = 480,
        jpeg_quality: int = 78,
    ) -> None:
        self._on_encoded = on_encoded
        self._min_interval = 1.0 / max_fps
        self._target_width = target_width
        self._jpeg_quality = jpeg_quality
        self._queue: queue.Queue[Optional[object]] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="gesture-preview", daemon=True)
        self._thread.start()

    def submit(self, frame_bgr) -> None:
        """Queue latest frame reference only — copy happens on the encoder thread."""
        if self._stop.is_set():
            return
        try:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put_nowait(frame_bgr)
        except queue.Full:
            pass

    def close(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2.0)

    def _encode(self, image_bgr) -> Optional[bytes]:
        height, width = image_bgr.shape[:2]
        target_w = self._target_width
        if width > target_w:
            target_h = max(1, int(height * (target_w / width)))
            preview = cv2.resize(image_bgr, (target_w, target_h), interpolation=cv2.INTER_AREA)
        else:
            preview = image_bgr

        ok, buf = cv2.imencode(
            ".jpg",
            preview,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
        )
        if not ok:
            return None
        return buf.tobytes()

    def _worker(self) -> None:
        last_send = 0.0
        pending_frame = None
        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.25)
            except queue.Empty:
                frame = None

            if frame is None and self._stop.is_set():
                break

            if frame is None:
                if pending_frame is None:
                    continue
            else:
                pending_frame = frame.copy()
                while True:
                    try:
                        pending_frame = self._queue.get_nowait().copy()
                    except queue.Empty:
                        break

            now = time.monotonic()
            if pending_frame is None or now - last_send < self._min_interval:
                continue

            jpeg = self._encode(pending_frame)
            pending_frame = None
            if jpeg:
                last_send = now
                try:
                    self._on_encoded(jpeg)
                except Exception:
                    pass
