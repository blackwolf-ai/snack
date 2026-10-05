"""Chat id and optional username allowlist."""

from __future__ import annotations

from snack.auth import Authorizer
from snack.config import TelegramConfig


def authorizer(
    chat_ids: set[int],
    usernames: set[str] | None = None,
) -> Authorizer:
    return Authorizer(
        TelegramConfig(
            token="123456789:AAEeeeeeeeeeeeeeeeeeeeeeee",
            allowed_chat_ids=frozenset(chat_ids),
            allowed_usernames=frozenset(usernames or ()),
        )
    )


def test_chat_id_allowlist_rejects_everyone_else() -> None:
    gate = authorizer({42, -1001})
    assert gate.check(42, None)
    assert gate.check(42, "anyone")
    assert gate.check(-1001, "groupmember")
    assert not gate.check(43, "anyone")
    assert not gate.check(None, "anyone")


def test_username_allowlist_is_case_insensitive_and_required() -> None:
    gate = authorizer({42}, {"admin"})
    assert gate.check(42, "Admin")
    assert gate.check(42, "@admin")
    assert not gate.check(42, "eve")
    assert not gate.check(42, None)
    assert not gate.check(99, "admin")


def test_empty_username_list_does_not_restrict_senders() -> None:
    gate = authorizer({42}, set())
    assert gate.check(42, None)
