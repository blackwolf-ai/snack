"""Structured logs must not keep the bot token."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from snack.logging_setup import JsonFormatter, redact, setup_logging


def test_redact_ignores_empty_secret() -> None:
    assert redact("hello world", ["", "world"]) == "hello [redacted]"


def test_formatter_redacts_token_and_emits_json() -> None:
    token = "123456789:AAEeeeeeeeeeeeeeeeeeeeeeee"
    formatter = JsonFormatter([token])
    record = logging.LogRecord(
        name="snack.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="connecting with %s",
        args=(token,),
        exc_info=None,
    )
    line = formatter.format(record)
    payload = json.loads(line)
    assert token not in line
    assert "[redacted]" in payload["msg"]
    assert payload["level"] == "INFO"


def test_file_log_redacts_token(tmp_path: Path) -> None:
    path = tmp_path / "snack.log"
    token = "123456789:AAEeeeeeeeeeeeeeeeeeeeeeee"
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        setup_logging("INFO", str(path), [token])
        logging.getLogger("snack.test").info("see %s", token)
    finally:
        root.handlers.clear()
        for handler in previous_handlers:
            root.addHandler(handler)
        root.setLevel(previous_level)
    text = path.read_text(encoding="utf-8")
    assert token not in text
    assert "[redacted]" in text
