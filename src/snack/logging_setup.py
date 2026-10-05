"""JSON logs to stdout and an optional file. Secrets are stripped from every line."""

from __future__ import annotations

import json
import logging
import sys
import time

_SKIP_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "taskName",
    "asctime",
}


def redact(text: str, secrets: list[str]) -> str:
    """Replace known secrets. Empty secrets are ignored so they cannot wipe the line."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in _SKIP_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        line = json.dumps(payload, default=str, ensure_ascii=False)
        return redact(line, self._secrets)


def setup_logging(level: str, log_file: str | None, secrets: list[str]) -> None:
    """Replace root handlers so the bot token cannot leak through httpx URLs."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    formatter = JsonFormatter(secrets)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    # python-telegram-bot logs request URLs that embed the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
