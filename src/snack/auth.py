"""Telegram allowlist. Fail closed: unknown chats never reach a command."""

from __future__ import annotations

from snack.config import TelegramConfig


class Authorizer:
    """Allow a chat only when its id is listed, and optionally its username."""

    def __init__(self, telegram: TelegramConfig) -> None:
        self._chat_ids = telegram.allowed_chat_ids
        self._usernames = telegram.allowed_usernames

    def check(self, chat_id: int | None, username: str | None) -> bool:
        if chat_id is None or chat_id not in self._chat_ids:
            return False
        if not self._usernames:
            return True
        if not username:
            return False
        normalized = username.strip().lstrip("@").casefold()
        return normalized in self._usernames
