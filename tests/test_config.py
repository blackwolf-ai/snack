"""Config loading, validation, and secret overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from snack.config import ConfigError, load_config, redacted_summary
from tests.helpers import TOKEN, write_config


def test_loads_whitelist_and_thresholds(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        services="\n  - name: web\n    unit: nginx.service\n",
        commands='\n  - name: disk\n    argv: ["df", "-h"]\n    timeout_seconds: 15\n',
        usernames='["@Admin"]',
    )
    cfg = load_config(path, environ={})
    assert cfg.hostname_override == "test-host"
    assert cfg.services["web"].unit == "nginx.service"
    assert cfg.commands["disk"].argv == ("df", "-h")
    assert cfg.commands["disk"].timeout_seconds == 15
    assert cfg.telegram.allowed_chat_ids == frozenset({42})
    assert cfg.telegram.allowed_usernames == frozenset({"admin"})
    assert cfg.thresholds.memory_percent == 85
    assert cfg.thresholds.disk_percent == 90
    summary = redacted_summary(cfg)
    assert TOKEN not in summary
    assert "telegram token: configured" in summary
    assert "web" in summary


def test_env_overrides_token_and_chat_ids(tmp_path: Path) -> None:
    path = write_config(tmp_path, chats="[42]")
    env_token = "999999:BBBBBBBBBBBBBBBBBBBBBBBB"
    cfg = load_config(
        path,
        environ={
            "TELEGRAM_BOT_TOKEN": env_token,
            "SNACK_ALLOWED_CHAT_IDS": "7, -1005",
        },
    )
    assert cfg.telegram.token == env_token
    assert cfg.telegram.allowed_chat_ids == frozenset({7, -1005})
    assert 42 not in cfg.telegram.allowed_chat_ids
    assert env_token not in redacted_summary(cfg)


def test_empty_token_can_come_from_env(tmp_path: Path) -> None:
    path = write_config(tmp_path, token="")
    cfg = load_config(
        path,
        environ={"TELEGRAM_BOT_TOKEN": "999999:BBBBBBBBBBBBBBBBBBBBBBBB"},
    )
    assert cfg.telegram.allowed_chat_ids == frozenset({42})


def test_require_telegram_fails_closed_without_allowlist(tmp_path: Path) -> None:
    path = write_config(tmp_path, chats="[]")
    with pytest.raises(ConfigError, match="allowed chat"):
        load_config(path, environ={}, require_telegram=True)


def test_example_config_is_structurally_valid() -> None:
    example = Path(__file__).resolve().parents[1] / "snack.example.yaml"
    cfg = load_config(example, environ={}, require_telegram=False)
    assert "disk" in cfg.commands
    assert cfg.commands["disk"].argv == ("df", "-h")
    assert "uptime" in cfg.commands
    assert cfg.services == {}
    assert cfg.thresholds.disk_percent == 90
    assert cfg.thresholds.memory_percent == 85
    with pytest.raises(ConfigError, match="token"):
        load_config(example, environ={}, require_telegram=True)


def test_rejects_shell_command_string(tmp_path: Path) -> None:
    path = write_config(tmp_path, commands='\n  - name: bad\n    argv: "df -h"\n')
    with pytest.raises(ConfigError, match="list of arguments"):
        load_config(path, environ={}, require_telegram=False)


def test_rejects_shell_c_and_env_wrapper(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        commands='\n  - name: bad\n    argv: ["bash", "-c", "echo hi"]\n',
    )
    with pytest.raises(ConfigError, match="arbitrary shell"):
        load_config(path, environ={}, require_telegram=False)

    wrapped = write_config(
        tmp_path,
        commands='\n  - name: bad\n    argv: ["/usr/bin/env", "bash", "-c", "id"]\n',
    )
    with pytest.raises(ConfigError, match="arbitrary shell"):
        load_config(wrapped, environ={}, require_telegram=False)


def test_allows_fixed_script_path(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        commands='\n  - name: check\n    argv: ["/usr/bin/python3", "/usr/local/sbin/check.py"]\n',
    )
    cfg = load_config(path, environ={}, require_telegram=False)
    assert cfg.commands["check"].argv[1] == "/usr/local/sbin/check.py"


def test_rejects_duplicate_names_unknown_keys_and_bad_interval(tmp_path: Path) -> None:
    dup = write_config(
        tmp_path,
        services="\n  - {name: nginx, unit: nginx.service}\n  - {name: nginx, unit: nginx.service}\n",
    )
    with pytest.raises(ConfigError, match="Duplicate service"):
        load_config(dup, environ={}, require_telegram=False)

    unknown = write_config(tmp_path, extra="telegram_extra: true\n")
    with pytest.raises(ConfigError, match="Unknown config setting"):
        load_config(unknown, environ={}, require_telegram=False)

    fast = write_config(tmp_path, interval="1")
    with pytest.raises(ConfigError, match="sample_interval"):
        load_config(fast, environ={}, require_telegram=False)


def test_rejects_unsafe_unit_and_bool_chat_id(tmp_path: Path) -> None:
    unsafe = write_config(
        tmp_path,
        services="\n  - name: bad\n    unit: ../nginx.service\n",
    )
    with pytest.raises(ConfigError, match="unit"):
        load_config(unsafe, environ={}, require_telegram=False)

    flagged = write_config(tmp_path, chats="[true]")
    with pytest.raises(ConfigError, match="chat id"):
        load_config(flagged, environ={}, require_telegram=False)


def test_disabled_threshold_and_missing_file(tmp_path: Path) -> None:
    text = (tmp_path / "soon.yaml")
    path = write_config(tmp_path)
    raw = path.read_text(encoding="utf-8").replace("cpu_percent: 90", "cpu_percent: null")
    path.write_text(raw, encoding="utf-8")
    cfg = load_config(path, environ={}, require_telegram=False)
    assert cfg.thresholds.cpu_percent is None
    with pytest.raises(ConfigError, match="Cannot read"):
        load_config(text, environ={}, require_telegram=False)
