"""Shared config fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

from snack.config import AgentConfig, load_config
from snack.health import HealthSnapshot

TOKEN = "123456789:AAEeeeeeeeeeeeeeeeeeeeeeee"


def write_config(
    tmp_path: Path,
    *,
    token: str = TOKEN,
    chats: str = "[42]",
    usernames: str = "[]",
    services: str = "[]",
    commands: str = "[]",
    interval: str = "60",
    hostname: str = "test-host",
    extra: str = "",
) -> Path:
    text = f"""
telegram:
  token: "{token}"
  allowed_chat_ids: {chats}
  allowed_usernames: {usernames}
agent:
  hostname: {hostname}
  sample_interval_seconds: {interval}
  disk_path: /
  log_level: INFO
  log_file: null
  notify_on_start: false
alerts:
  cooldown_seconds: 900
  cpu_percent: 90
  memory_percent: 85
  disk_percent: 90
  load_per_cpu: 2.0
limits:
  output_max_bytes: 3500
  default_timeout_seconds: 30
services: {services}
commands: {commands}
{extra}
"""
    path = tmp_path / "snack.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def load_test_config(tmp_path: Path, **kwargs: str) -> AgentConfig:
    path = write_config(tmp_path, **kwargs)
    return load_config(path, environ={})


def snapshot(**overrides: object) -> HealthSnapshot:
    base: dict[str, object] = {
        "hostname": "test-host",
        "system": "Linux test",
        "uptime_seconds": 3661,
        "cpu_percent": 10.0,
        "cpu_count": 4,
        "memory_percent": 40.0,
        "memory_used_bytes": 1024,
        "memory_total_bytes": 4096,
        "disk_path": "/",
        "disk_percent": 50.0,
        "disk_used_bytes": 1024,
        "disk_total_bytes": 2048,
        "disk_error": None,
        "load_1": 0.4,
        "load_5": 0.3,
        "load_15": 0.2,
    }
    base.update(overrides)
    return HealthSnapshot(**base)  # type: ignore[arg-type]
