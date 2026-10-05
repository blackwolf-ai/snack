"""CLI config check and local health sample."""

from __future__ import annotations

from pathlib import Path

from snack.cli import run
from snack.health import sample_health
from tests.helpers import TOKEN, write_config


def test_check_config_hides_the_token(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)
    code = run(["check-config", "--config", str(path)])
    captured = capsys.readouterr()
    assert code == 0
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    assert "telegram token: configured" in captured.out
    assert "allowed chat ids: 42" in captured.out


def test_check_config_accepts_global_flag(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path)
    code = run(["--config", str(path), "check-config"])
    assert code == 0
    assert "config:" in capsys.readouterr().out


def test_missing_config_on_run_is_an_error(tmp_path: Path, capsys) -> None:
    code = run(["run", "--config", str(tmp_path / "missing.yaml")])
    captured = capsys.readouterr()
    assert code == 2
    assert "Cannot read" in captured.err


def test_sample_uses_config_hostname(tmp_path: Path, capsys) -> None:
    path = write_config(tmp_path, token="")
    code = run(["sample", "--config", str(path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Host: test-host" in captured.out
    assert "Memory:" in captured.out


def test_sample_without_config_still_prints_health(tmp_path: Path, capsys) -> None:
    code = run(["sample", "--config", str(tmp_path / "absent.yaml")])
    captured = capsys.readouterr()
    assert code == 0
    assert "sampling disk /" in captured.err
    assert "health" in captured.out


def test_live_sample_has_basic_fields() -> None:
    snap = sample_health("/")
    assert snap.hostname
    assert snap.memory_total_bytes > 0
    assert snap.cpu_count >= 1
    assert snap.uptime_seconds >= 0
    assert 0 <= snap.memory_percent <= 100
