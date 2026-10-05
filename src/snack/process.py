"""Run a fixed argument vector with a timeout. This module never invokes a shell."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    output: str
    timed_out: bool
    spawn_error: str | None


def truncate_output(text: str, max_bytes: int) -> str:
    """Cut text so its UTF-8 form fits in max_bytes, including a truncation marker."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text
    marker = "\n…[truncated]"
    budget = max_bytes - len(marker.encode("utf-8"))
    if budget <= 0:
        return marker
    clipped = raw[:budget].decode("utf-8", errors="ignore")
    return clipped + marker


def combine_output(stdout: bytes, stderr: bytes, max_bytes: int) -> str:
    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if out and err:
        text = f"{out}\nstderr:\n{err}"
    else:
        text = out or err
    return truncate_output(text, max_bytes)


def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Stop the process and, on POSIX, the session it leads.

    Whitelisted commands are trusted, but a timeout must still reap children
    spawned by a script. This is ordinary process control, not concealment:
    the snack process itself stays in the normal process list.
    """
    if proc.pid is None:
        return
    if sys.platform != "win32":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


async def run_argv(
    argv: list[str],
    *,
    timeout: float,
    output_max_bytes: int,
) -> ProcessResult:
    if not argv or not all(isinstance(arg, str) and arg for arg in argv):
        return ProcessResult(None, "", False, "Refusing to run an empty argument vector")
    popen_kwargs: dict[str, object] = {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if sys.platform != "win32":
        # Own session so a timeout can signal the whole group.
        popen_kwargs["start_new_session"] = True
    try:
        proc = await asyncio.create_subprocess_exec(argv[0], *argv[1:], **popen_kwargs)
    except FileNotFoundError:
        return ProcessResult(None, "", False, f"Executable not found: {argv[0]}")
    except OSError as exc:
        reason = exc.strerror or exc.__class__.__name__
        return ProcessResult(None, "", False, f"Failed to start process: {reason}")

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        _terminate(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except TimeoutError:
            pass
        return ProcessResult(None, "", True, None)
    output = combine_output(stdout or b"", stderr or b"", output_max_bytes)
    return ProcessResult(proc.returncode, output, False, None)
