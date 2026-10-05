"""Alert thresholds and cooldown behavior."""

from __future__ import annotations

from snack.alerts import AlertTracker, evaluate_thresholds
from snack.config import ThresholdConfig
from snack.health import format_uptime
from tests.helpers import snapshot


def thresholds(**overrides: object) -> ThresholdConfig:
    base: dict[str, object] = {
        "cpu_percent": 90.0,
        "memory_percent": 85.0,
        "disk_percent": 90.0,
        "load_per_cpu": 2.0,
        "cooldown_seconds": 100.0,
    }
    base.update(overrides)
    return ThresholdConfig(**base)  # type: ignore[arg-type]


def test_boundaries_and_disabled_checks() -> None:
    hot = snapshot(cpu_percent=90.0, memory_percent=85.0, disk_percent=90.0, load_1=8.0, cpu_count=4)
    active = evaluate_thresholds(hot, thresholds())
    assert set(active) == {"cpu", "memory", "disk", "load"}
    assert "90.0%" in active["cpu"]
    assert "90.0%" in active["disk"]

    warm = snapshot(cpu_percent=89.9, memory_percent=84.9, disk_percent=89.9, load_1=7.9, cpu_count=4)
    assert evaluate_thresholds(warm, thresholds()) == {}

    disabled = evaluate_thresholds(
        hot,
        thresholds(cpu_percent=None, memory_percent=None, disk_percent=None, load_per_cpu=None),
    )
    assert disabled == {}


def test_missing_disk_or_load_does_not_alert() -> None:
    snap = snapshot(disk_percent=None, disk_error="not found", load_1=None, cpu_percent=99, memory_percent=99)
    active = evaluate_thresholds(snap, thresholds())
    assert set(active) == {"cpu", "memory"}


def test_cooldown_reminder_recovery_and_flap() -> None:
    tracker = AlertTracker(100)
    active = {"disk": "disk / at 95.0% (threshold 90%)"}
    first = tracker.poll(active, now=0)
    assert first == ["ALERT disk: disk / at 95.0% (threshold 90%)"]
    assert tracker.poll(active, now=50) == []
    again = tracker.poll(active, now=100)
    assert again == ["ALERT disk: disk / at 95.0% (threshold 90%) (still over threshold)"]

    recovered = tracker.poll({}, now=101)
    assert recovered == ["RECOVERED disk: back under the threshold"]
    assert tracker.poll(active, now=150) == []
    refired = tracker.poll(active, now=201)
    assert refired == ["ALERT disk: disk / at 95.0% (threshold 90%)"]


def test_multiple_keys_are_sorted_and_recover_independently() -> None:
    tracker = AlertTracker(100)
    messages = tracker.poll({"memory": "mem", "cpu": "cpu high"}, now=0)
    assert messages == ["ALERT cpu: cpu high", "ALERT memory: mem"]
    later = tracker.poll({"memory": "mem"}, now=10)
    assert later == ["RECOVERED cpu: back under the threshold"]


def test_format_uptime() -> None:
    assert format_uptime(3661) == "1h 1m"
    assert format_uptime(45) == "0m 45s"
    assert format_uptime(90061) == "1d 1h 1m"
