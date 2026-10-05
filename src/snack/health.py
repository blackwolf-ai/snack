"""Host health samples. CPU, memory, disk, load, uptime, hostname, and OS."""

from __future__ import annotations

import os
import platform
import socket
import time
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class HealthSnapshot:
    hostname: str
    system: str
    uptime_seconds: float
    cpu_percent: float
    cpu_count: int
    memory_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    disk_path: str
    disk_percent: float | None
    disk_used_bytes: int | None
    disk_total_bytes: int | None
    disk_error: str | None
    load_1: float | None
    load_5: float | None
    load_15: float | None


def sample_health(disk_path: str = "/", hostname_override: str | None = None) -> HealthSnapshot:
    """Read one sample. cpu_percent(interval=None) is the delta since the previous call.

    The alert loop primes psutil once at startup so the first real sample is not a
    meaningless zero. On-demand /health calls still return the delta since the last
    read in this process, which is what an operator wants while the agent is running.
    """
    memory = psutil.virtual_memory()
    cpu_count = psutil.cpu_count(logical=True) or os.cpu_count() or 1
    try:
        load = os.getloadavg()
    except (AttributeError, OSError):
        load = None

    disk_percent: float | None = None
    disk_used: int | None = None
    disk_total: int | None = None
    disk_error: str | None = None
    try:
        usage = psutil.disk_usage(disk_path)
    except OSError as exc:
        disk_error = exc.strerror or exc.__class__.__name__
    else:
        disk_percent = float(usage.percent)
        disk_used = int(usage.used)
        disk_total = int(usage.total)

    return HealthSnapshot(
        hostname=hostname_override or socket.gethostname(),
        system=f"{platform.system()} {platform.release()}",
        uptime_seconds=max(0.0, time.time() - psutil.boot_time()),
        cpu_percent=float(psutil.cpu_percent(interval=None)),
        cpu_count=cpu_count,
        memory_percent=float(memory.percent),
        memory_used_bytes=int(memory.used),
        memory_total_bytes=int(memory.total),
        disk_path=disk_path,
        disk_percent=disk_percent,
        disk_used_bytes=disk_used,
        disk_total_bytes=disk_total,
        disk_error=disk_error,
        load_1=None if load is None else float(load[0]),
        load_5=None if load is None else float(load[1]),
        load_15=None if load is None else float(load[2]),
    )


def format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    if not days and not hours:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def format_health(snap: HealthSnapshot) -> str:
    if snap.disk_percent is None:
        disk_line = f"Disk ({snap.disk_path}): unavailable ({snap.disk_error or 'unknown error'})"
    else:
        disk_line = (
            f"Disk ({snap.disk_path}): {snap.disk_percent:.1f}% "
            f"({format_bytes(snap.disk_used_bytes or 0)} / {format_bytes(snap.disk_total_bytes or 0)})"
        )
    if snap.load_1 is None:
        load_line = "Load: unavailable on this platform"
    else:
        per_cpu = snap.load_1 / snap.cpu_count if snap.cpu_count else snap.load_1
        load_line = (
            f"Load: {snap.load_1:.2f} {snap.load_5:.2f} {snap.load_15:.2f} "
            f"(1m per CPU {per_cpu:.2f})"
        )
    return "\n".join(
        [
            "health",
            f"Host: {snap.hostname}",
            f"OS: {snap.system}",
            f"Uptime: {format_uptime(snap.uptime_seconds)}",
            f"CPU: {snap.cpu_percent:.1f}% ({snap.cpu_count} cores)",
            (
                f"Memory: {snap.memory_percent:.1f}% "
                f"({format_bytes(snap.memory_used_bytes)} / {format_bytes(snap.memory_total_bytes)})"
            ),
            disk_line,
            load_line,
        ]
    )


def format_status(snap: HealthSnapshot) -> str:
    disk = "n/a" if snap.disk_percent is None else f"{snap.disk_percent:.1f}%"
    load = "n/a" if snap.load_1 is None else f"{snap.load_1:.2f}"
    return (
        f"monitoring active on {snap.hostname}\n"
        f"up {format_uptime(snap.uptime_seconds)} | "
        f"cpu {snap.cpu_percent:.1f}% | mem {snap.memory_percent:.1f}% | "
        f"disk {disk} | load {load}"
    )
