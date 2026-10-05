"""Keep developer environment variables from changing test config."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_snack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SNACK_ALLOWED_CHAT_IDS", raising=False)
    monkeypatch.delenv("SNACK_CONFIG", raising=False)
