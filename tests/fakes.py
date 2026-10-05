"""Duck-typed Telegram update objects for handler tests."""

from __future__ import annotations


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append(text)


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeUser:
    def __init__(self, user_id: int = 7, username: str | None = "admin") -> None:
        self.id = user_id
        self.username = username


class FakeUpdate:
    def __init__(self, chat_id: int, username: str | None = "admin") -> None:
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser(username=username)
        self.effective_message = FakeMessage()
        self.message = self.effective_message


class FakeContext:
    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or []
