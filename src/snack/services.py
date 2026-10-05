"""Start, stop, restart, and query a whitelist of systemd units.

macOS and Windows do not pretend to control services. Callers get a clear
message and health monitoring continues to work.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from snack.config import ServiceSpec
from snack.process import ProcessResult, run_argv

Executor = Callable[..., Awaitable[ProcessResult]]
ACTIONS = frozenset({"start", "stop", "restart", "status"})


@dataclass(frozen=True)
class ServiceResult:
    ok: bool
    name: str
    action: str
    output: str
    error: str | None = None


def systemctl_argv(binary: str, action: str, unit: str) -> list[str]:
    """Build a systemctl invocation. action and unit are already validated."""
    if action == "status":
        return [binary, "status", unit, "--no-pager", "--lines=20"]
    return [binary, action, unit, "--no-pager"]


def systemd_supported(platform: str | None = None) -> bool:
    plat = sys.platform if platform is None else platform
    if plat != "linux":
        return False
    return Path("/run/systemd/system").is_dir()


class ServiceController:
    def __init__(
        self,
        services: dict[str, ServiceSpec],
        *,
        output_max_bytes: int,
        timeout_seconds: float,
        platform: str | None = None,
        systemd: bool | None = None,
        executor: Executor | None = None,
    ) -> None:
        self._services = services
        self._output_max_bytes = output_max_bytes
        self._timeout = timeout_seconds
        self.platform = sys.platform if platform is None else platform
        self.supported = systemd_supported(self.platform) if systemd is None else systemd
        self._executor = executor or run_argv
        self._lock = asyncio.Lock()

    def names(self) -> list[str]:
        return sorted(self._services)

    async def action(self, name: str, action: str) -> ServiceResult:
        if action not in ACTIONS:
            return ServiceResult(False, name, action, "", error=f"Unsupported action '{action}'")
        spec = self._services.get(name)
        if spec is None:
            known = ", ".join(self.names()) or "(none)"
            return ServiceResult(
                False,
                name,
                action,
                "",
                error=f"'{name}' is not a whitelisted service. Known: {known}",
            )
        if not self.supported:
            return ServiceResult(
                False,
                name,
                action,
                "",
                error=(
                    "Service control requires Linux with systemd. "
                    f"This host is '{self.platform}'. Health monitoring still works."
                ),
            )
        binary = "systemctl" if self._executor is not run_argv else shutil.which("systemctl")
        if not binary:
            return ServiceResult(
                False,
                name,
                action,
                "",
                error="systemctl was not found on PATH.",
            )
        argv = systemctl_argv(binary, action, spec.unit)
        async with self._lock:
            completed = await self._executor(
                argv,
                timeout=self._timeout,
                output_max_bytes=self._output_max_bytes,
            )
        return _from_process(spec.name, action, completed)


def _from_process(name: str, action: str, completed: ProcessResult) -> ServiceResult:
    if completed.spawn_error:
        return ServiceResult(False, name, action, "", error=completed.spawn_error)
    if completed.timed_out:
        return ServiceResult(False, name, action, completed.output, error="Timed out")
    # `systemctl status` exits non-zero when a unit is inactive. The query still worked.
    if action == "status":
        output = completed.output
        if completed.exit_code not in (0, None):
            suffix = f"(systemctl exit {completed.exit_code})"
            output = f"{output}\n{suffix}".strip() if output else suffix
        return ServiceResult(True, name, action, output, error=None)
    if completed.exit_code == 0:
        return ServiceResult(True, name, action, completed.output, error=None)
    return ServiceResult(
        False,
        name,
        action,
        completed.output,
        error=f"Exited {completed.exit_code}",
    )


def format_service_result(result: ServiceResult) -> str:
    if result.action == "status":
        body = result.output.strip() or result.error or "(no output)"
        return f"{result.name}:\n{body}"
    if result.ok:
        extra = f"\n{result.output.strip()}" if result.output.strip() else ""
        return f"{result.action} {result.name}: ok{extra}"
    detail = result.error or "failed"
    extra = f"\n{result.output.strip()}" if result.output.strip() else ""
    return f"{result.action} {result.name}: {detail}{extra}"
