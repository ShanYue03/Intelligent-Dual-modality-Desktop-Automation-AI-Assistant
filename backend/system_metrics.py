"""System CPU and memory probes for the dashboard (psutil)."""

from __future__ import annotations

from typing import Tuple

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

CpuSnapshot = Tuple[float, float]


def get_cpu_snapshot() -> CpuSnapshot:
    """Return (total_time, idle_time) from cumulative OS CPU counters."""
    if psutil is None:
        return 0.0, 0.0
    cpu_times = psutil.cpu_times()
    return float(sum(cpu_times)), float(cpu_times.idle)


def compute_cpu_percent(window_start: CpuSnapshot, window_end: CpuSnapshot) -> float:
    """
    CPU utilization (%) = 100 * (total_delta - idle_delta) / total_delta
    over the interval between two snapshots.
    """
    start_total, start_idle = window_start
    end_total, end_idle = window_end
    total_delta = end_total - start_total
    idle_delta = end_idle - start_idle
    if total_delta <= 0:
        return 0.0
    active_delta = total_delta - idle_delta
    return max((active_delta / total_delta) * 100.0, 0.0)


def get_process_memory_percent() -> float:
    """This backend process RSS as a percentage of total system memory."""
    if psutil is None:
        return 0.0
    try:
        return float(psutil.Process().memory_percent())
    except Exception:
        return 0.0


def capture_session_metrics(cpu_start: CpuSnapshot) -> tuple[float, float]:
    """CPU % over the session window and process memory % at session end."""
    cpu_end = get_cpu_snapshot()
    cpu_percent = compute_cpu_percent(cpu_start, cpu_end)
    memory_percent = get_process_memory_percent()
    return cpu_percent, memory_percent
