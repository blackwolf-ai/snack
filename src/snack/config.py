"""Load snack.yaml and apply environment overrides for secrets.

TELEGRAM_BOT_TOKEN and SNACK_ALLOWED_CHAT_IDS replace the file values when set.
The token is never included in error messages or in redacted_summary().
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@:_\\.-]{0,127}$")
_SHELLS = {
    "sh",
    "bash",
    "dash",
    "zsh",
    "ksh",
    "fish",
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "php",
}
_SHELL_FLAGS = {"-c", "-lc", "/c", "-e", "-command", "/command"}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_ROOT_KEYS = {"telegram", "agent", "alerts", "limits", "services", "commands"}
_TELEGRAM_KEYS = {"token", "allowed_chat_ids", "allowed_usernames"}
_AGENT_KEYS = {
    "hostname",
    "sample_interval_seconds",
    "disk_path",
    "log_level",
    "log_file",
    "notify_on_start",
}
_ALERT_KEYS = {
    "cooldown_seconds",
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "load_per_cpu",
}
_LIMIT_KEYS = {"output_max_bytes", "default_timeout_seconds"}
_SERVICE_KEYS = {"name", "unit"}
_COMMAND_KEYS = {"name", "argv", "timeout_seconds"}


class ConfigError(ValueError):
    """snack.yaml or an environment override is missing or invalid."""


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    allowed_chat_ids: frozenset[int]
    allowed_usernames: frozenset[str]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    unit: str


@dataclass(frozen=True)
class ThresholdConfig:
    cpu_percent: float | None
    memory_percent: float | None
    disk_percent: float | None
    load_per_cpu: float | None
    cooldown_seconds: float


@dataclass(frozen=True)
class LimitsConfig:
    output_max_bytes: int
    default_timeout_seconds: float


@dataclass(frozen=True)
class AgentConfig:
    config_path: Path
    hostname_override: str | None
    sample_interval_seconds: float
    disk_path: str
    log_level: str
    log_file: str | None
    notify_on_start: bool
    telegram: TelegramConfig
    thresholds: ThresholdConfig
    limits: LimitsConfig
    services: dict[str, ServiceSpec]
    commands: dict[str, CommandSpec]


def load_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    require_telegram: bool = True,
) -> AgentConfig:
    """Load YAML from path. environ defaults to os.environ."""
    config_path = Path(path)
    env = os.environ if environ is None else environ
    data = _read_yaml(config_path)
    _check_keys(data, _ROOT_KEYS, "config")

    telegram_raw = _section(data, "telegram", {})
    agent_raw = _section(data, "agent", {})
    alerts_raw = _section(data, "alerts", {})
    limits_raw = _section(data, "limits", {})
    _check_keys(telegram_raw, _TELEGRAM_KEYS, "telegram")
    _check_keys(agent_raw, _AGENT_KEYS, "agent")
    _check_keys(alerts_raw, _ALERT_KEYS, "alerts")
    _check_keys(limits_raw, _LIMIT_KEYS, "limits")

    limits = _parse_limits(limits_raw)
    services = _parse_services(data.get("services", []))
    commands = _parse_commands(data.get("commands", []), limits.default_timeout_seconds)
    thresholds = _parse_thresholds(alerts_raw)
    telegram = _parse_telegram(telegram_raw, env, require_telegram=require_telegram)

    hostname = agent_raw.get("hostname")
    hostname_override: str | None
    if hostname is None:
        hostname_override = None
    elif isinstance(hostname, str) and hostname.strip() and "\n" not in hostname and "\r" not in hostname:
        hostname_override = hostname.strip()
        if len(hostname_override) > 253:
            raise ConfigError("agent.hostname is too long")
    else:
        raise ConfigError("agent.hostname must be a string or null")

    interval = _number(agent_raw.get("sample_interval_seconds", 60), "agent.sample_interval_seconds")
    if interval < 5 or interval > 86400:
        raise ConfigError("agent.sample_interval_seconds must be between 5 and 86400")

    disk_path = agent_raw.get("disk_path", "/")
    if not isinstance(disk_path, str) or not disk_path.strip():
        raise ConfigError("agent.disk_path must be a non-empty string")

    log_level = str(agent_raw.get("log_level", "INFO")).upper()
    if log_level not in _LOG_LEVELS:
        raise ConfigError("agent.log_level must be DEBUG, INFO, WARNING, or ERROR")

    log_file_raw = agent_raw.get("log_file")
    if log_file_raw is None:
        log_file = None
    elif isinstance(log_file_raw, str) and log_file_raw.strip():
        log_file = log_file_raw.strip()
    else:
        raise ConfigError("agent.log_file must be a path or null")

    notify = agent_raw.get("notify_on_start", True)
    if not isinstance(notify, bool):
        raise ConfigError("agent.notify_on_start must be true or false")

    return AgentConfig(
        config_path=config_path,
        hostname_override=hostname_override,
        sample_interval_seconds=interval,
        disk_path=disk_path,
        log_level=log_level,
        log_file=log_file,
        notify_on_start=notify,
        telegram=telegram,
        thresholds=thresholds,
        limits=limits,
        services=services,
        commands=commands,
    )


def redacted_summary(cfg: AgentConfig) -> str:
    """Local config summary. The bot token is not included."""
    if cfg.telegram.token:
        token_line = "telegram token: configured"
    else:
        token_line = "telegram token: missing"
    ids = ", ".join(str(chat_id) for chat_id in sorted(cfg.telegram.allowed_chat_ids)) or "(none)"
    if cfg.telegram.allowed_usernames:
        users = ", ".join(sorted(cfg.telegram.allowed_usernames))
    else:
        users = "(any user in the allowed chats)"
    services = ", ".join(sorted(cfg.services)) or "(none)"
    commands = ", ".join(sorted(cfg.commands)) or "(none)"
    thresholds = cfg.thresholds
    return "\n".join(
        [
            f"config: {cfg.config_path}",
            f"hostname override: {cfg.hostname_override or '(machine hostname)'}",
            f"sample interval: {thresholds_number(cfg.sample_interval_seconds)}s",
            f"disk path: {cfg.disk_path}",
            (
                "alerts: "
                f"cpu>={_fmt_optional(thresholds.cpu_percent)} "
                f"memory>={_fmt_optional(thresholds.memory_percent)} "
                f"disk>={_fmt_optional(thresholds.disk_percent)} "
                f"load_per_cpu>={_fmt_optional(thresholds.load_per_cpu)} "
                f"cooldown={thresholds_number(thresholds.cooldown_seconds)}s"
            ),
            f"services: {services}",
            f"commands: {commands}",
            token_line,
            f"allowed chat ids: {ids}",
            f"allowed usernames: {users}",
            f"log level: {cfg.log_level}",
            f"log file: {cfg.log_file or '(stdout only)'}",
            f"notify on start: {str(cfg.notify_on_start).lower()}",
        ]
    )


def thresholds_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "off"
    return thresholds_number(value)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config {path}: {exc.strerror or exc.__class__.__name__}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping")
    return data


def _section(data: dict[str, Any], key: str, default: dict[str, Any]) -> dict[str, Any]:
    value = data.get(key, default)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _check_keys(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise ConfigError(f"Unknown {path} setting(s): {', '.join(extra)}")


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{path} must be a number")
    return float(value)


def _optional_number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    return _number(value, path)


def _percent(value: Any, path: str) -> float | None:
    number = _optional_number(value, path)
    if number is None:
        return None
    if number <= 0 or number > 100:
        raise ConfigError(f"{path} must be greater than 0 and at most 100, or null to disable")
    return number


def _parse_limits(raw: Mapping[str, Any]) -> LimitsConfig:
    output_max = raw.get("output_max_bytes", 3500)
    if isinstance(output_max, bool) or not isinstance(output_max, int):
        raise ConfigError("limits.output_max_bytes must be an integer")
    if output_max < 64 or output_max > 4000:
        raise ConfigError("limits.output_max_bytes must be between 64 and 4000")
    timeout = _number(raw.get("default_timeout_seconds", 30), "limits.default_timeout_seconds")
    if timeout <= 0 or timeout > 3600:
        raise ConfigError("limits.default_timeout_seconds must be between 1 and 3600")
    return LimitsConfig(output_max_bytes=output_max, default_timeout_seconds=timeout)


def _parse_thresholds(raw: Mapping[str, Any]) -> ThresholdConfig:
    cooldown = _number(raw.get("cooldown_seconds", 900), "alerts.cooldown_seconds")
    if cooldown < 1 or cooldown > 7 * 86400:
        raise ConfigError("alerts.cooldown_seconds must be between 1 and 604800")
    load = _optional_number(raw.get("load_per_cpu", 2.0), "alerts.load_per_cpu")
    if load is not None and load <= 0:
        raise ConfigError("alerts.load_per_cpu must be greater than 0, or null to disable")
    return ThresholdConfig(
        cpu_percent=_percent(raw.get("cpu_percent", 90), "alerts.cpu_percent"),
        memory_percent=_percent(raw.get("memory_percent", 85), "alerts.memory_percent"),
        disk_percent=_percent(raw.get("disk_percent", 90), "alerts.disk_percent"),
        load_per_cpu=load,
        cooldown_seconds=cooldown,
    )


def _parse_telegram(
    raw: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    require_telegram: bool,
) -> TelegramConfig:
    token = raw.get("token") or ""
    if not isinstance(token, str):
        raise ConfigError("telegram.token must be a string")
    token = token.strip()
    env_token = env.get("TELEGRAM_BOT_TOKEN")
    if env_token is not None and env_token.strip():
        token = env_token.strip()

    env_ids = env.get("SNACK_ALLOWED_CHAT_IDS")
    if env_ids is not None and env_ids.strip():
        chat_ids = _parse_env_chat_ids(env_ids)
    else:
        chat_ids = _parse_chat_id_list(raw.get("allowed_chat_ids", []), "telegram.allowed_chat_ids")
    usernames = _parse_usernames(raw.get("allowed_usernames", []))

    if require_telegram:
        if not token or not _TOKEN_RE.fullmatch(token):
            raise ConfigError(
                "Telegram bot token is missing or not in the expected form. "
                "Set telegram.token or TELEGRAM_BOT_TOKEN. "
                "Get a token from @BotFather. The token was not logged."
            )
        if not chat_ids:
            raise ConfigError(
                "At least one allowed chat id is required. "
                "Set telegram.allowed_chat_ids or SNACK_ALLOWED_CHAT_IDS."
            )
    elif token and not _TOKEN_RE.fullmatch(token):
        raise ConfigError(
            "telegram.token is set but not in the expected form. "
            "Leave it empty to use TELEGRAM_BOT_TOKEN. The value was not logged."
        )

    return TelegramConfig(
        token=token,
        allowed_chat_ids=frozenset(chat_ids),
        allowed_usernames=frozenset(usernames),
    )


def _parse_env_chat_ids(raw: str) -> list[int]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise ConfigError("SNACK_ALLOWED_CHAT_IDS is set but empty")
    ids: list[int] = []
    for part in parts:
        if not re.fullmatch(r"-?\d+", part):
            raise ConfigError("SNACK_ALLOWED_CHAT_IDS must be comma-separated integers")
        ids.append(int(part))
    return ids


def _parse_chat_id_list(value: Any, path: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{path} must be a list of integer chat ids")
    ids: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and re.fullmatch(r"-?\d+", item.strip()):
            ids.append(int(item.strip()))
            continue
        if isinstance(item, bool) or not isinstance(item, int):
            raise ConfigError(f"{path}[{index}] must be an integer chat id")
        ids.append(item)
    return ids


def _parse_usernames(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError("telegram.allowed_usernames must be a list")
    names: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ConfigError(f"telegram.allowed_usernames[{index}] must be a string")
        name = item.strip().lstrip("@").casefold()
        if not re.fullmatch(r"[a-z0-9_]{1,32}", name):
            raise ConfigError(
                f"telegram.allowed_usernames[{index}] is not a Telegram username"
            )
        names.append(name)
    return names


def _parse_services(value: Any) -> dict[str, ServiceSpec]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ConfigError("services must be a list")
    services: dict[str, ServiceSpec] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"services[{index}] must be a mapping")
        _check_keys(item, _SERVICE_KEYS, f"services[{index}]")
        name = _identifier(item.get("name"), f"services[{index}].name")
        unit = item.get("unit")
        if not isinstance(unit, str) or not _UNIT_RE.fullmatch(unit):
            raise ConfigError(
                f"services[{index}].unit must be a systemd unit name such as nginx.service"
            )
        if unit.startswith("-") or "/" in unit or ".." in unit:
            raise ConfigError(f"services[{index}].unit is not a safe unit name")
        if name in services:
            raise ConfigError(f"Duplicate service name '{name}'")
        services[name] = ServiceSpec(name=name, unit=unit)
    return services


def _parse_commands(value: Any, default_timeout: float) -> dict[str, CommandSpec]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise ConfigError("commands must be a list")
    commands: dict[str, CommandSpec] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"commands[{index}] must be a mapping")
        _check_keys(item, _COMMAND_KEYS, f"commands[{index}]")
        name = _identifier(item.get("name"), f"commands[{index}].name")
        argv = _parse_argv(item.get("argv"), f"commands[{index}].argv")
        if "timeout_seconds" in item:
            timeout = _number(item.get("timeout_seconds"), f"commands[{index}].timeout_seconds")
        else:
            timeout = default_timeout
        if timeout <= 0 or timeout > 3600:
            raise ConfigError(f"commands[{index}].timeout_seconds must be between 1 and 3600")
        if name in commands:
            raise ConfigError(f"Duplicate command name '{name}'")
        commands[name] = CommandSpec(name=name, argv=tuple(argv), timeout_seconds=timeout)
    return commands


def _parse_argv(value: Any, path: str) -> list[str]:
    if isinstance(value, str):
        raise ConfigError(
            f"{path} must be a list of arguments, not a shell string. "
            "Example: [\"df\", \"-h\"]"
        )
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{path} must be a non-empty list of strings")
    argv: list[str] = []
    for index, arg in enumerate(value):
        if not isinstance(arg, str) or not arg or "\x00" in arg:
            raise ConfigError(f"{path}[{index}] must be a non-empty string")
        argv.append(arg)
    _reject_shell(argv, path)
    return argv


def _reject_shell(argv: list[str], path: str) -> None:
    """Block interpreter -c style entries, including `env bash -c`.

    A fixed script path such as ["/usr/bin/python3", "/usr/local/sbin/check.py"]
    stays allowed. This is a config guardrail: argv is still trusted admin input,
    and snack never interpolates Telegram text into it.
    """
    bases = {Path(arg).name.lower() for arg in argv}
    flags = {arg.lower() for arg in argv}
    if bases & _SHELLS and flags & _SHELL_FLAGS:
        raise ConfigError(
            f"{path} starts a shell or interpreter with a command string. "
            "snack does not allow arbitrary shell. "
            "Point argv at a fixed binary or script path instead."
        )


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ConfigError(
            f"{path} must be 1-64 characters of letters, digits, '.', '_' or '-'"
        )
    return value
