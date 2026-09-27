"""Shared fakes. Tests never touch the network: OpenAI and Telegram are stubbed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import Settings
from bot.handlers import BotHandlers
from bot.llm import LLMClient
from bot.memory import ConversationStore
from bot.ratelimit import SlidingWindowRateLimiter


def make_settings(**overrides) -> Settings:
    values = {
        "telegram_token": "123456:TEST-TOKEN",
        "openai_api_key": "sk-test",
        "stream_edit_interval": 0.0,
        "db_path": ":memory:",
    }
    values.update(overrides)
    return Settings(**values)


class FakeLLM:
    """Stands in for LLMClient: returns canned replies or raises a given error."""

    def __init__(self, reply: str = "Hello there!", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[dict]] = []

    async def complete(self, conversation):
        self.calls.append(conversation)
        if self.error:
            raise self.error
        return self.reply

    async def stream(self, conversation):
        self.calls.append(conversation)
        for word in self.reply.split(" "):
            yield word + " "
        if self.error:
            raise self.error


def make_update(text: str = "hi", chat_id: int = 42, user_id: int = 7):
    sent_messages: list[MagicMock] = []

    async def reply_text(value: str):
        sent = MagicMock()
        sent.text = value
        sent.edits = []

        async def edit_text(new_value: str):
            sent.edits.append(new_value)
            sent.text = new_value

        sent.edit_text = edit_text
        sent_messages.append(sent)
        return sent

    message = SimpleNamespace(
        text=text, chat_id=chat_id, reply_text=AsyncMock(side_effect=reply_text)
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
        sent=sent_messages,
    )
    return update


@pytest.fixture
def context():
    return SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))


@pytest.fixture
def store():
    s = ConversationStore(":memory:", max_messages_per_chat=50)
    yield s
    s.close()


@pytest.fixture
def build_handlers(store):
    def factory(llm=None, **settings_overrides) -> BotHandlers:
        settings = make_settings(**settings_overrides)
        limiter = SlidingWindowRateLimiter(
            settings.rate_limit_messages, settings.rate_limit_window_seconds
        )
        return BotHandlers(settings, llm or FakeLLM(), store, limiter)

    return factory


@pytest.fixture
def fake_openai():
    """An AsyncOpenAI double exposing ``chat.completions.create``."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def llm_client(fake_openai) -> LLMClient:
    return LLMClient(make_settings(system_prompt="SYSTEM"), client=fake_openai)
