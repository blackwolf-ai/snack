"""Telegram handlers enforce the allowlist before any whitelist action."""

from __future__ import annotations

from pathlib import Path

from snack.bot import SnackHandlers, build_application
from snack.commands import CommandResult
from snack.config import ServiceSpec, load_config
from snack.services import ServiceController, ServiceResult
from tests.fakes import FakeContext, FakeUpdate
from tests.helpers import snapshot, write_config


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def names(self) -> list[str]:
        return ["disk"]

    async def run(self, name: str) -> CommandResult:
        self.calls.append(name)
        return CommandResult(True, name, 0, "filesystems", None, False)


class FakeServices:
    supported = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def names(self) -> list[str]:
        return ["nginx"]

    async def action(self, name: str, action: str) -> ServiceResult:
        self.calls.append((name, action))
        return ServiceResult(True, name, action, "active", None)


def handlers(tmp_path: Path, **config_kwargs: str) -> tuple[SnackHandlers, FakeCommands, FakeServices]:
    path = write_config(
        tmp_path,
        services="\n  - name: nginx\n    unit: nginx.service\n",
        commands='\n  - name: disk\n    argv: ["df", "-h"]\n',
        **config_kwargs,
    )
    cfg = load_config(path, environ={})
    commands = FakeCommands()
    services = FakeServices()
    bound = SnackHandlers(
        cfg,
        command_runner=commands,  # type: ignore[arg-type]
        service_controller=services,  # type: ignore[arg-type]
        sample=lambda: snapshot(),
    )
    return bound, commands, services


async def test_unauthorized_chat_cannot_run_commands(tmp_path: Path) -> None:
    bound, commands, services = handlers(tmp_path)
    update = FakeUpdate(999)
    await bound.run(update, FakeContext(["disk"]))  # type: ignore[arg-type]
    await bound.start_service(update, FakeContext(["nginx"]))  # type: ignore[arg-type]
    assert update.effective_message.replies == ["Not authorized.", "Not authorized."]
    assert commands.calls == []
    assert services.calls == []


async def test_username_restriction_is_applied(tmp_path: Path) -> None:
    bound, commands, _services = handlers(tmp_path, usernames='["admin"]')
    denied = FakeUpdate(42, username="eve")
    await bound.health(denied, FakeContext())  # type: ignore[arg-type]
    assert denied.effective_message.replies == ["Not authorized."]
    assert commands.calls == []


async def test_run_and_service_commands_use_only_the_name(tmp_path: Path) -> None:
    bound, commands, services = handlers(tmp_path)
    update = FakeUpdate(42)
    await bound.run(update, FakeContext(["disk"]))  # type: ignore[arg-type]
    await bound.run(update, FakeContext(["disk", "--flag"]))  # type: ignore[arg-type]
    await bound.start_service(update, FakeContext(["nginx"]))  # type: ignore[arg-type]
    await bound.restart_service(update, FakeContext())  # type: ignore[arg-type]
    assert commands.calls == ["disk"]
    assert services.calls == [("nginx", "start")]
    text = "\n".join(update.effective_message.replies)
    assert "[test-host] run disk (exit 0)" in text
    assert "Extra arguments are rejected" in text
    assert "[test-host] start nginx: ok" in text
    assert "Usage: /restart_service NAME" in text


async def test_health_help_and_whoami(tmp_path: Path) -> None:
    bound, _commands, _services = handlers(tmp_path)
    update = FakeUpdate(42, username="admin")
    await bound.health(update, FakeContext())  # type: ignore[arg-type]
    await bound.status(update, FakeContext())  # type: ignore[arg-type]
    await bound.help(update, FakeContext())  # type: ignore[arg-type]
    await bound.whoami(update, FakeContext())  # type: ignore[arg-type]
    replies = update.effective_message.replies
    assert replies[0].startswith("[test-host] health")
    assert "CPU:" in replies[0]
    assert "monitoring active on test-host" in replies[1]
    assert "/run NAME" in replies[2]
    assert "disk" in replies[2]
    assert "nginx" in replies[2]
    assert "chat id: 42" in replies[3]
    assert "authorized: yes" in replies[3]


async def test_unknown_names_never_spawn_a_process(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        services="\n  - name: nginx\n    unit: nginx.service\n",
        commands='\n  - name: disk\n    argv: ["df", "-h"]\n',
    )
    cfg = load_config(path, environ={})
    bound = SnackHandlers(cfg, sample=lambda: snapshot())
    update = FakeUpdate(42)
    await bound.run(update, FakeContext(["not-real"]))  # type: ignore[arg-type]
    await bound.stop_service(update, FakeContext(["not-real"]))  # type: ignore[arg-type]
    text = "\n".join(update.effective_message.replies)
    assert "not a whitelisted command" in text
    assert "not a whitelisted service" in text
    assert "nginx" in text


async def test_services_listing_on_macos_does_not_call_systemctl(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        services="\n  - name: nginx\n    unit: nginx.service\n",
    )
    cfg = load_config(path, environ={})

    async def boom(*args, **kwargs):
        raise AssertionError("systemctl should not run")

    controller = ServiceController(
        {"nginx": ServiceSpec("nginx", "nginx.service")},
        output_max_bytes=500,
        timeout_seconds=5,
        platform="darwin",
        systemd=False,
        executor=boom,
    )
    bound = SnackHandlers(cfg, service_controller=controller, sample=lambda: snapshot())
    update = FakeUpdate(42)
    await bound.services_cmd(update, FakeContext())  # type: ignore[arg-type]
    await bound.start_service(update, FakeContext(["nginx"]))  # type: ignore[arg-type]
    text = "\n".join(update.effective_message.replies)
    assert "systemd" in text
    assert "nginx" in text
    assert "darwin" in text


def test_application_registers_the_command_whitelist(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    cfg = load_config(path, environ={})
    app = build_application(cfg)
    registered: set[str] = set()
    for group in app.handlers.values():
        for handler in group:
            registered.update(getattr(handler, "commands", set()))
    assert {
        "help",
        "whoami",
        "status",
        "health",
        "services",
        "start_service",
        "stop_service",
        "restart_service",
        "run",
    } <= registered
