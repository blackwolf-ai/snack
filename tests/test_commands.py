"""Command whitelist, argv execution, timeout, and output cap."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from snack.commands import CommandRunner
from snack.config import CommandSpec
from snack.process import ProcessResult, run_argv, truncate_output


def _runner(executor=None) -> CommandRunner:
    commands = {
        "disk": CommandSpec("disk", ("df", "-h"), 15),
        "uptime": CommandSpec("uptime", ("uptime",), 10),
    }
    return CommandRunner(commands, output_max_bytes=200, executor=executor)


async def test_unknown_command_does_not_execute() -> None:
    async def boom(*args, **kwargs):
        raise AssertionError(f"executor should not be called: {args} {kwargs}")

    result = await _runner(boom).run("disk; rm -rf /")
    assert not result.ok
    assert "not a whitelisted command" in (result.error or "")


async def test_known_command_receives_the_configured_argv_list() -> None:
    seen: dict[str, object] = {}

    async def capture(argv, *, timeout, output_max_bytes):
        seen["argv"] = argv
        seen["timeout"] = timeout
        seen["output_max_bytes"] = output_max_bytes
        return ProcessResult(0, "ok\n", False, None)

    result = await _runner(capture).run("disk")
    assert result.ok
    assert result.output.strip() == "ok"
    assert seen["argv"] == ["df", "-h"]
    assert isinstance(seen["argv"], list)
    assert seen["timeout"] == 15


async def test_nonzero_exit_is_reported() -> None:
    async def fail(argv, *, timeout, output_max_bytes):
        return ProcessResult(2, "nope", False, None)

    result = await _runner(fail).run("uptime")
    assert not result.ok
    assert result.exit_code == 2
    assert result.error == "Exited 2"


def test_truncate_output_respects_utf8_budget() -> None:
    text = "é" * 100
    clipped = truncate_output(text, max_bytes=40)
    assert clipped.endswith("…[truncated]")
    assert len(clipped.encode("utf-8")) <= 40


async def test_real_process_echo_timeout_and_missing_binary() -> None:
    echo = shutil.which("echo")
    sleep = shutil.which("sleep")
    if not echo or not sleep:
        pytest.skip("echo or sleep is not installed")

    echoed = await run_argv([echo, "snack-ok"], timeout=5, output_max_bytes=100)
    assert echoed.exit_code == 0
    assert echoed.output == "snack-ok"
    assert not echoed.timed_out

    long = await run_argv([echo, "x" * 500], timeout=5, output_max_bytes=64)
    assert long.output.endswith("…[truncated]")
    assert len(long.output.encode("utf-8")) <= 64

    timed = await run_argv([sleep, "30"], timeout=1, output_max_bytes=100)
    assert timed.timed_out
    assert timed.exit_code is None

    missing = await run_argv(["/no/such/snack-binary"], timeout=2, output_max_bytes=100)
    assert missing.spawn_error
    assert "not found" in missing.spawn_error


async def test_runner_reports_timeout_from_real_sleep() -> None:
    sleep = shutil.which("sleep")
    if not sleep:
        pytest.skip("sleep is not installed")
    runner = CommandRunner(
        {"slow": CommandSpec("slow", (sleep, "30"), 1)},
        output_max_bytes=100,
    )
    result = await runner.run("slow")
    assert result.timed_out
    assert result.error == "Timed out after 1s"


def test_source_tree_has_no_shell_execution() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    text = "\n".join(path.read_text(encoding="utf-8") for path in src.rglob("*.py"))
    assert "shell=True" not in text
    assert "create_subprocess_shell" not in text
    assert "os.system(" not in text
    assert "subprocess.Popen" not in text
