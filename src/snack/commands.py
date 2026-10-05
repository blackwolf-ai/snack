"""Run commands by name. The name selects a fixed argv from config; nothing else."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from snack.config import CommandSpec
from snack.process import ProcessResult, run_argv

Executor = Callable[..., Awaitable[ProcessResult]]


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    name: str
    exit_code: int | None
    output: str
    error: str | None = None
    timed_out: bool = False


class CommandRunner:
    def __init__(
        self,
        commands: dict[str, CommandSpec],
        output_max_bytes: int,
        executor: Executor | None = None,
    ) -> None:
        self._commands = commands
        self._output_max_bytes = output_max_bytes
        self._executor = executor or run_argv
        # One command at a time. The whitelist is small and admin-facing.
        self._lock = asyncio.Lock()

    def names(self) -> list[str]:
        return sorted(self._commands)

    async def run(self, name: str) -> CommandResult:
        spec = self._commands.get(name)
        if spec is None:
            known = ", ".join(self.names()) or "(none)"
            return CommandResult(
                ok=False,
                name=name,
                exit_code=None,
                output="",
                error=f"'{name}' is not a whitelisted command. Known: {known}",
            )
        async with self._lock:
            return await self._execute(spec)

    async def _execute(self, spec: CommandSpec) -> CommandResult:
        completed = await self._executor(
            list(spec.argv),
            timeout=spec.timeout_seconds,
            output_max_bytes=self._output_max_bytes,
        )
        result = _from_process(spec.name, completed)
        if result.timed_out:
            return CommandResult(
                ok=False,
                name=spec.name,
                exit_code=None,
                output=result.output,
                error=f"Timed out after {spec.timeout_seconds:g}s",
                timed_out=True,
            )
        return result


def _from_process(name: str, completed: ProcessResult) -> CommandResult:
    if completed.spawn_error:
        return CommandResult(
            ok=False,
            name=name,
            exit_code=None,
            output="",
            error=completed.spawn_error,
        )
    if completed.timed_out:
        return CommandResult(
            ok=False,
            name=name,
            exit_code=None,
            output=completed.output,
            error="Timed out",
            timed_out=True,
        )
    code = completed.exit_code
    ok = code == 0
    return CommandResult(
        ok=ok,
        name=name,
        exit_code=code,
        output=completed.output,
        error=None if ok else f"Exited {code}",
    )


def format_command_result(result: CommandResult) -> str:
    if result.error and not result.output:
        return f"run {result.name}: {result.error}"
    header = f"run {result.name}"
    if result.exit_code is not None:
        header += f" (exit {result.exit_code})"
    if result.error:
        header += f"\n{result.error}"
    body = result.output.strip() or "(no output)"
    return f"{header}\n{body}"
