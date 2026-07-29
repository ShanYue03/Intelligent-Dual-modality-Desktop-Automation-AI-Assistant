import csv
from datetime import datetime, timezone
from pathlib import Path

from .enums import Gest

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


class GestureAuditLogger:
    """
    Append-only audit log for gesture recognition events.

    Latency and CPU utilization follow the evaluation reference:
    ``D:\\Documents\\FYP\\Gesture_Control\\evaluation\\evaluator.py``
    - Latency: wall time for finger-state update + gesture classification (seconds).
    - CPU: system-wide utilization from ``psutil.cpu_times()`` delta between events.
    """

    CSV_HEADERS = ["timestamp", "gesture_action", "Latency", "CPU Utilization"]
    DEFAULT_CSV = Path(__file__).resolve().parent.parent / "gesture_auditlog.csv"

    MODULE_SWITCH_VOICE_LABEL = "Launch Voice Assistant"

    _GESTURE_LABELS = {
        Gest.V_GEST: "Cursor movement",
        Gest.FIST: "Drag and drop",
        Gest.MID: "Left-click",
        Gest.INDEX: "Right-click",
        Gest.TWO_FINGER_CLOSED: "Double click",
        Gest.PINCH_MINOR: "Pinch gestures",
        Gest.PINCH_MAJOR: "Pinch gestures",
        Gest.THUMBS_UP: MODULE_SWITCH_VOICE_LABEL,
    }

    def __init__(self, output_csv: Path | str | None = None):
        self.output_csv = Path(output_csv) if output_csv else self.DEFAULT_CSV
        self.last_saved_label = None
        self.cpu_window_start = self._get_system_cpu_snapshot()

    @classmethod
    def gesture_label(cls, gesture):
        return cls._GESTURE_LABELS.get(gesture)

    @classmethod
    def event_label(cls, zoom_consumed, active_gesture):
        if zoom_consumed:
            return "Zoom gestures"
        return cls.gesture_label(active_gesture)

    @staticmethod
    def active_gesture(zoom_consumed, minor_gest, major_gest):
        if zoom_consumed:
            return Gest.PALM
        if minor_gest == Gest.PINCH_MINOR:
            return minor_gest
        return major_gest

    @staticmethod
    def _get_system_cpu_snapshot():
        if psutil is None:
            return 0.0, 0.0
        cpu_times = psutil.cpu_times()
        total_time = sum(cpu_times)
        idle_time = cpu_times.idle
        return total_time, idle_time

    @staticmethod
    def compute_cpu_percent(window_start, window_end):
        start_total, start_idle = window_start
        end_total, end_idle = window_end
        total_delta = end_total - start_total
        idle_delta = end_idle - start_idle
        if total_delta <= 0:
            return 0.0
        active_delta = total_delta - idle_delta
        return max((active_delta / total_delta) * 100.0, 0.0)

    def _ensure_csv_exists(self):
        if self.output_csv.exists():
            return
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        with self.output_csv.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(self.CSV_HEADERS)

    def _write_event(self, gesture_action, latency_sec, cpu_percent):
        self._ensure_csv_exists()
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        with self.output_csv.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [
                    timestamp,
                    gesture_action,
                    f"{latency_sec:.6f}",
                    f"{cpu_percent:.4f}",
                ]
            )

    def record_frame(self, zoom_consumed, minor_gest, major_gest, latency_sec):
        """
        Log one row when the recognized gesture action changes (transition-based).
        Returns CPU percent for the elapsed window (for callers that need it).
        """
        cpu_window_end = self._get_system_cpu_snapshot()
        cpu_percent = self.compute_cpu_percent(self.cpu_window_start, cpu_window_end)

        active = self.active_gesture(zoom_consumed, minor_gest, major_gest)
        label = self.event_label(zoom_consumed, active)
        if label and label != self.last_saved_label:
            try:
                self._write_event(label, latency_sec, cpu_percent)
            except OSError:
                pass
            self.last_saved_label = label
            self.cpu_window_start = self._get_system_cpu_snapshot()

        return cpu_percent
