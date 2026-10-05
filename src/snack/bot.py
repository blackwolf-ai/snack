"""Telegram command interface. Unauthorized chats are rejected before any action."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import psutil
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from snack.alerts import AlertTracker, evaluate_thresholds
from snack.auth import Authorizer
from snack.commands import CommandRunner, format_command_result
from snack.config import NAME_RE, AgentConfig
from snack.health import format_health, format_status, sample_health
from snack.services import ServiceController, format_service_result

logger = logging.getLogger("snack.bot")

TELEGRAM_LIMIT = 4096
Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def tag(hostname: str, body: str) -> str:
    """Prefix every reply so a later multi-machine setup can tell hosts apart."""
    return f"[{hostname}] {body}"


@dataclass(frozen=True)
class SeenChat:
    chat_id: int
    chat_type: str
    username: str | None


class SnackHandlers:
    def __init__(
        self,
        cfg: AgentConfig,
        *,
        authorizer: Authorizer | None = None,
        command_runner: CommandRunner | None = None,
        service_controller: ServiceController | None = None,
        alert_tracker: AlertTracker | None = None,
        sample: Callable[[], object] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.cfg = cfg
        self.authorizer = authorizer or Authorizer(cfg.telegram)
        self.commands = command_runner or CommandRunner(
            cfg.commands,
            cfg.limits.output_max_bytes,
        )
        self.services = service_controller or ServiceController(
            cfg.services,
            output_max_bytes=cfg.limits.output_max_bytes,
            timeout_seconds=cfg.limits.default_timeout_seconds,
        )
        self.tracker = alert_tracker or AlertTracker(cfg.thresholds.cooldown_seconds)
        self._sample = sample or (
            lambda: sample_health(cfg.disk_path, cfg.hostname_override)
        )
        self._clock = clock or time.monotonic
        self._alert_task: asyncio.Task[None] | None = None
        self.hostname = cfg.hostname_override or socket.gethostname()

    def command_map(self) -> dict[str, Handler]:
        return {
            "start": self.start,
            "help": self.help,
            "whoami": self.whoami,
            "status": self.status,
            "health": self.health,
            "services": self.services_cmd,
            "start_service": self.start_service,
            "stop_service": self.stop_service,
            "restart_service": self.restart_service,
            "run": self.run,
        }

    async def post_init(self, app: Application) -> None:
        try:
            await app.bot.set_my_commands(
                [
                    BotCommand("help", "Show whitelisted actions"),
                    BotCommand("whoami", "Show your chat id and this host"),
                    BotCommand("status", "Short health summary"),
                    BotCommand("health", "CPU, memory, disk, load, uptime"),
                    BotCommand("services", "Whitelisted service status"),
                    BotCommand("start_service", "Start a whitelisted service"),
                    BotCommand("stop_service", "Stop a whitelisted service"),
                    BotCommand("restart_service", "Restart a whitelisted service"),
                    BotCommand("run", "Run a named whitelisted command"),
                ]
            )
        except Exception as exc:
            logger.warning(
                "could not register bot commands",
                extra={"error_type": type(exc).__name__},
            )
        if self.cfg.notify_on_start:
            await self._notify_start(app)
        # Prime the CPU counter so the first real sample is a delta, not a zero.
        await asyncio.to_thread(psutil.cpu_percent, None)
        self._alert_task = _spawn(app, self._alert_loop(app))

    async def post_shutdown(self, app: Application) -> None:
        if self._alert_task is not None:
            self._alert_task.cancel()
            self._alert_task = None

    async def on_error(self, update: object, context: object) -> None:
        err = getattr(context, "error", None)
        logger.error(
            "telegram handler failed",
            extra={"error_type": type(err).__name__ if err else "unknown"},
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await self._reply(update, tag(self.hostname, self._help_body()))

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await self._reply(update, tag(self.hostname, self._help_body()))

    async def whoami(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        chat = update.effective_chat
        user = update.effective_user
        username = f"@{user.username}" if user is not None and user.username else "(none)"
        user_id = user.id if user is not None else "(none)"
        chat_id = chat.id if chat is not None else "(none)"
        text = (
            f"chat id: {chat_id}\n"
            f"username: {username}\n"
            f"user id: {user_id}\n"
            f"host: {self.hostname}\n"
            "authorized: yes"
        )
        await self._reply(update, tag(self.hostname, text))

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        snap = await asyncio.to_thread(self._sample)
        await self._reply(update, tag(snap.hostname, format_status(snap)))

    async def health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        snap = await asyncio.to_thread(self._sample)
        await self._reply(update, tag(snap.hostname, format_health(snap)))

    async def services_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        names = self.services.names()
        if not names:
            await self._reply(
                update,
                tag(self.hostname, "No services are configured in the whitelist."),
            )
            return
        if not self.services.supported:
            listed = ", ".join(names)
            await self._reply(
                update,
                tag(
                    self.hostname,
                    "Service control requires Linux with systemd. "
                    f"Configured services: {listed}",
                ),
            )
            return
        blocks = []
        for name in names:
            result = await self.services.action(name, "status")
            blocks.append(format_service_result(result))
        await self._reply(update, tag(self.hostname, "services\n" + "\n\n".join(blocks)))

    async def start_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._service(update, context, "start")

    async def stop_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._service(update, context, "stop")

    async def restart_service(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._service(update, context, "restart")

    async def run(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        name, error = _one_name(context)
        if error or name is None:
            await self._reply(
                update,
                tag(self.hostname, f"Usage: /run NAME\n{error}"),
            )
            return
        result = await self.commands.run(name)
        await self._reply(update, tag(self.hostname, format_command_result(result)))

    async def _service(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
    ) -> None:
        if not await self._guard(update):
            return
        name, error = _one_name(context)
        if error or name is None:
            await self._reply(
                update,
                tag(self.hostname, f"Usage: /{action}_service NAME\n{error}"),
            )
            return
        result = await self.services.action(name, action)
        await self._reply(update, tag(self.hostname, format_service_result(result)))

    async def _guard(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        chat_id = chat.id if chat is not None else None
        username = user.username if user is not None else None
        if self.authorizer.check(chat_id, username):
            return True
        logger.warning(
            "rejected telegram command",
            extra={"chat_id": chat_id, "username": username},
        )
        message = update.effective_message
        if message is not None:
            await message.reply_text("Not authorized.")
        return False

    async def _reply(self, update: Update, text: str) -> None:
        message = update.effective_message
        if message is None:
            return
        start = 0
        while start < len(text):
            await message.reply_text(text[start : start + TELEGRAM_LIMIT])
            start += TELEGRAM_LIMIT

    async def _notify_start(self, app: Application) -> None:
        services = ", ".join(self.services.names()) or "(none)"
        commands = ", ".join(self.commands.names()) or "(none)"
        text = tag(
            self.hostname,
            "snack monitoring active\n"
            "Visible admin agent for machines you administer.\n"
            f"Services: {services}\n"
            f"Commands: {commands}",
        )
        await self._broadcast(app, text)

    async def _alert_loop(self, app: Application) -> None:
        interval = self.cfg.sample_interval_seconds
        while True:
            try:
                snap = await asyncio.to_thread(self._sample)
                active = evaluate_thresholds(snap, self.cfg.thresholds)
                for body in self.tracker.poll(active, self._clock()):
                    await self._broadcast(app, tag(snap.hostname, body))
                    logger.info("alert", extra={"alert": body.split(":", 1)[0]})
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("alert loop iteration failed")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    async def _broadcast(self, app: Application, text: str) -> None:
        for chat_id in sorted(self.cfg.telegram.allowed_chat_ids):
            try:
                await app.bot.send_message(chat_id=chat_id, text=text[:TELEGRAM_LIMIT])
            except Exception as exc:
                logger.warning(
                    "failed to send telegram message",
                    extra={"chat_id": chat_id, "error_type": type(exc).__name__},
                )

    def _help_body(self) -> str:
        services = ", ".join(self.services.names()) or "(none configured)"
        commands = ", ".join(self.commands.names()) or "(none configured)"
        return (
            "snack — visible system monitor\n"
            "This bot answers only an allowlist of chats.\n"
            "\n"
            "Commands:\n"
            "/help — this message\n"
            "/whoami — your chat id and this host\n"
            "/status — short health summary\n"
            "/health — CPU, memory, disk, load, uptime\n"
            "/services — whitelisted services and their status\n"
            "/start_service NAME\n"
            "/stop_service NAME\n"
            "/restart_service NAME\n"
            "/run NAME — run one named command\n"
            "\n"
            f"Services: {services}\n"
            f"Commands: {commands}\n"
            "\n"
            "Names must match the config exactly. There is no shell."
        )


def build_application(cfg: AgentConfig, handlers: SnackHandlers | None = None) -> Application:
    bound = handlers or SnackHandlers(cfg)
    app = (
        Application.builder()
        .token(cfg.telegram.token)
        .post_init(bound.post_init)
        .post_shutdown(bound.post_shutdown)
        .build()
    )
    for name, callback in bound.command_map().items():
        app.add_handler(CommandHandler(name, callback))
    app.add_error_handler(bound.on_error)
    return app


async def list_recent_chats(token: str) -> tuple[str, list[SeenChat]]:
    """Local setup helper. Listing a chat id does not add it to the allowlist."""
    from telegram import Bot

    bot = Bot(token)
    async with bot:
        me = await bot.get_me()
        updates = await bot.get_updates(timeout=0, allowed_updates=["message"])
    seen: dict[int, SeenChat] = {}
    for update in updates:
        message = update.message
        if message is None or message.chat is None:
            continue
        username = message.from_user.username if message.from_user else None
        seen[message.chat.id] = SeenChat(message.chat.id, str(message.chat.type), username)
    label = f"@{me.username}" if me.username else str(me.id)
    return label, [seen[key] for key in sorted(seen)]


def _spawn(app: Application, coro: Awaitable[None]) -> asyncio.Task[None]:
    create = getattr(app, "create_task", None)
    if callable(create):
        return create(coro)
    return asyncio.get_running_loop().create_task(coro)


def _one_name(context: object) -> tuple[str | None, str | None]:
    args = list(getattr(context, "args", None) or [])
    if len(args) != 1:
        return None, "Give exactly one name. Extra arguments are rejected."
    if not NAME_RE.fullmatch(args[0]):
        return None, "That name is not a configured identifier."
    return args[0], None
