"""Service whitelist and systemd / non-systemd behavior."""

from __future__ import annotations

from snack.config import ServiceSpec
from snack.process import ProcessResult
from snack.services import ServiceController, systemctl_argv


def _controller(executor, *, systemd: bool = True, platform: str = "linux") -> ServiceController:
    return ServiceController(
        {"web": ServiceSpec("web", "nginx.service")},
        output_max_bytes=500,
        timeout_seconds=5,
        platform=platform,
        systemd=systemd,
        executor=executor,
    )


def test_systemctl_argv_uses_the_configured_unit() -> None:
    assert systemctl_argv("/bin/systemctl", "restart", "nginx.service") == [
        "/bin/systemctl",
        "restart",
        "nginx.service",
        "--no-pager",
    ]
    assert systemctl_argv("systemctl", "status", "nginx.service")[-2:] == [
        "--no-pager",
        "--lines=20",
    ]


async def test_unknown_service_is_refused_before_execution() -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("systemctl should not run")

    result = await _controller(boom).action("nginx", "start")
    assert not result.ok
    assert "not a whitelisted service" in (result.error or "")
    assert "web" in (result.error or "")


async def test_whitelisted_name_maps_to_configured_unit() -> None:
    seen: dict[str, object] = {}

    async def capture(argv, *, timeout, output_max_bytes):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return ProcessResult(0, "", False, None)

    result = await _controller(capture).action("web", "restart")
    assert result.ok
    assert result.error is None
    assert seen["argv"] == ["systemctl", "restart", "nginx.service", "--no-pager"]
    assert seen["timeout"] == 5


async def test_status_accepts_inactive_exit_code() -> None:
    async def inactive(argv, *, timeout, output_max_bytes):
        return ProcessResult(3, "inactive", False, None)

    result = await _controller(inactive).action("web", "status")
    assert result.ok
    assert "inactive" in result.output
    assert "exit 3" in result.output


async def test_failed_restart_is_not_ok() -> None:
    async def fail(argv, *, timeout, output_max_bytes):
        return ProcessResult(1, "permission denied", False, None)

    result = await _controller(fail).action("web", "stop")
    assert not result.ok
    assert result.error == "Exited 1"


async def test_non_linux_degrades_without_calling_systemctl() -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("systemctl should not run")

    result = await _controller(boom, systemd=False, platform="darwin").action("web", "start")
    assert not result.ok
    assert "systemd" in (result.error or "")
    assert "darwin" in (result.error or "")


async def test_bad_action_string() -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("should not run")

    result = await _controller(boom).action("web", "reload")
    assert not result.ok
    assert "Unsupported action" in (result.error or "")
