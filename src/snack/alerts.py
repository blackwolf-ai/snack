"""Threshold checks and per-alert cooldowns so a stuck disk does not spam Telegram."""

from __future__ import annotations

from snack.config import ThresholdConfig
from snack.health import HealthSnapshot


def evaluate_thresholds(snap: HealthSnapshot, thresholds: ThresholdConfig) -> dict[str, str]:
    """Return alert-key -> message for metrics currently at or over their threshold.

    A threshold of None disables that check. Missing samples (no disk, no load
    average) are skipped rather than treated as a breach.
    """
    active: dict[str, str] = {}
    if thresholds.cpu_percent is not None and snap.cpu_percent >= thresholds.cpu_percent:
        active["cpu"] = f"CPU {snap.cpu_percent:.1f}% (threshold {thresholds.cpu_percent:g}%)"
    if thresholds.memory_percent is not None and snap.memory_percent >= thresholds.memory_percent:
        active["memory"] = (
            f"memory {snap.memory_percent:.1f}% (threshold {thresholds.memory_percent:g}%)"
        )
    if (
        thresholds.disk_percent is not None
        and snap.disk_percent is not None
        and snap.disk_percent >= thresholds.disk_percent
    ):
        active["disk"] = (
            f"disk {snap.disk_path} {snap.disk_percent:.1f}% "
            f"(threshold {thresholds.disk_percent:g}%)"
        )
    if (
        thresholds.load_per_cpu is not None
        and snap.load_1 is not None
        and snap.cpu_count > 0
        and (snap.load_1 / snap.cpu_count) >= thresholds.load_per_cpu
    ):
        per_cpu = snap.load_1 / snap.cpu_count
        active["load"] = (
            f"load {snap.load_1:.2f} on {snap.cpu_count} CPUs "
            f"({per_cpu:.2f} per CPU, threshold {thresholds.load_per_cpu:g})"
        )
    return active


class AlertTracker:
    """Send on transition to breach, remind after the cooldown, and send one recovery.

    A breach that clears and returns inside the cooldown is suppressed. That
    keeps a metric flapping around the threshold from flooding the chat.
    """

    def __init__(self, cooldown_seconds: float) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}
        self._active: set[str] = set()

    def poll(self, active: dict[str, str], now: float) -> list[str]:
        messages: list[str] = []
        for key in sorted(self._active):
            if key not in active:
                messages.append(f"RECOVERED {key}: back under the threshold")
                self._active.remove(key)
                self._last_sent[key] = now
        for key in sorted(active):
            last = self._last_sent.get(key)
            cooled = last is None or (now - last) >= self.cooldown_seconds
            if not cooled:
                continue
            if key in self._active:
                messages.append(f"ALERT {key}: {active[key]} (still over threshold)")
            else:
                messages.append(f"ALERT {key}: {active[key]}")
                self._active.add(key)
            self._last_sent[key] = now
        return messages
