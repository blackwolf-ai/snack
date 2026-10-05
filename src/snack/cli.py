"""Command line entry point. `snack` and `snack run` start the visible agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

from snack import __version__
from snack.bot import build_application, list_recent_chats
from snack.config import ConfigError, load_config, redacted_summary
from snack.health import format_health, sample_health
from snack.logging_setup import setup_logging

logger = logging.getLogger("snack.cli")


def main(argv: list[str] | None = None) -> None:
    sys.exit(run(argv))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snack",
        description="Visible, consent-based system monitor controlled via Telegram.",
    )
    parser.add_argument("--version", action="version", version=f"snack {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        dest="config",
        default=None,
        help="Path to snack.yaml (default: ./snack.yaml or $SNACK_CONFIG)",
    )
    sub = parser.add_subparsers(dest="command")

    def add_sub(name: str, help_text: str) -> None:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("-c", "--config", dest="config_subcommand", default=None)

    add_sub("run", "Start the agent (this is the default)")
    add_sub("check-config", "Validate config and print a redacted summary")
    add_sub("sample", "Print one local health sample and exit")
    add_sub("chats", "List chat IDs that have recently messaged the bot")

    args = parser.parse_args(argv)
    command = args.command or "run"
    selected = getattr(args, "config_subcommand", None) or args.config
    if selected is None:
        selected = os.environ.get("SNACK_CONFIG", "snack.yaml")
    path = Path(selected)

    if command == "sample":
        return _cmd_sample(path)
    try:
        cfg = load_config(path, require_telegram=True)
    except ConfigError as exc:
        print(f"snack: {exc}", file=sys.stderr)
        return 2
    if command == "check-config":
        print(redacted_summary(cfg))
        return 0
    if command == "chats":
        return _cmd_chats(cfg)
    return _cmd_run(cfg)


def print_banner(config_path: Path, hostname: str, allowlist_size: int) -> None:
    print(
        "\n".join(
            [
                "============================================================",
                " snack — consent-based system monitor",
                " This process is visible on purpose.",
                " Use it only on machines you own or administer.",
                " Monitoring active.",
                f" config: {config_path}",
                f" host:   {hostname}",
                f" allowlist: {allowlist_size} chat id(s)",
                "============================================================",
            ]
        )
    )


def _cmd_sample(path: Path) -> int:
    disk = "/"
    override = None
    if path.exists():
        try:
            cfg = load_config(path, require_telegram=False)
        except ConfigError as exc:
            print(f"snack: {exc}", file=sys.stderr)
            return 2
        disk = cfg.disk_path
        override = cfg.hostname_override
    else:
        print(f"snack: no config at {path}; sampling disk /", file=sys.stderr)
    print(format_health(sample_health(disk, override)))
    return 0


def _cmd_chats(cfg) -> int:
    from telegram.error import Conflict, InvalidToken, TelegramError

    try:
        label, chats = asyncio.run(list_recent_chats(cfg.telegram.token))
    except InvalidToken:
        print("snack: Telegram rejected the bot token. It was not logged.", file=sys.stderr)
        return 1
    except Conflict:
        print(
            "snack: the agent is already polling. Stop it, then run snack chats.",
            file=sys.stderr,
        )
        return 1
    except TelegramError as exc:
        print(f"snack: Telegram error ({type(exc).__name__}).", file=sys.stderr)
        return 1
    print(f"Bot {label}")
    if not chats:
        print("No recent messages.")
        print("Send /start to the bot in Telegram, then run snack chats again.")
        print("If the agent is running, stop it first. getUpdates cannot share the token.")
        return 0
    for chat in chats:
        who = f"@{chat.username}" if chat.username else "(no username)"
        print(f"chat_id={chat.chat_id} type={chat.chat_type} from={who}")
    print("Add those chat_id values to telegram.allowed_chat_ids or SNACK_ALLOWED_CHAT_IDS.")
    return 0


def _cmd_run(cfg) -> int:
    try:
        setup_logging(cfg.log_level, cfg.log_file, [cfg.telegram.token])
    except OSError as exc:
        print(f"snack: cannot open log file ({exc.strerror}).", file=sys.stderr)
        return 1

    hostname = cfg.hostname_override or socket.gethostname()
    print_banner(cfg.config_path, hostname, len(cfg.telegram.allowed_chat_ids))
    logger.info(
        "monitoring active",
        extra={
            "hostname": hostname,
            "config": str(cfg.config_path),
            "allowlist_size": len(cfg.telegram.allowed_chat_ids),
            "services": len(cfg.services),
            "commands": len(cfg.commands),
        },
    )
    code = 0
    try:
        app = build_application(cfg)
        # Drop messages sent while the agent was down so a queued
        # /restart_service cannot fire later by surprise.
        app.run_polling(drop_pending_updates=True, allowed_updates=["message"])
    except KeyboardInterrupt:
        code = 0
    except Exception as exc:
        # Do not print the exception text. InvalidToken includes the bot token.
        code = _telegram_failure(exc)
    finally:
        print("snack monitoring stopped.")
        logger.info("monitoring stopped")
    return code


def _telegram_failure(exc: BaseException) -> int:
    from telegram.error import Conflict, InvalidToken, TelegramError

    if isinstance(exc, InvalidToken):
        print("snack: Telegram rejected the bot token. It was not logged.", file=sys.stderr)
        return 1
    if isinstance(exc, Conflict):
        print(
            "snack: another client is already polling this bot token. Stop it and retry.",
            file=sys.stderr,
        )
        return 1
    if isinstance(exc, TelegramError):
        print(f"snack: Telegram error ({type(exc).__name__}).", file=sys.stderr)
        return 1
    print(f"snack: stopped ({type(exc).__name__}).", file=sys.stderr)
    return 1
