from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, Message, Update

from bot.formatting import TELEGRAM_MAX_LENGTH
from bot.handlers import GENERIC_ERROR_TEXT, INTERRUPTED_SUFFIX, RESET_TEXT, STREAM_CURSOR
from bot.llm import LLMError
from tests.conftest import FakeLLM, make_update


async def test_reply_is_sent_and_exchange_stored(build_handlers, context, store):
    handlers = build_handlers(FakeLLM("Hello there!"), stream_replies=False)
    update = make_update("hi")

    await handlers.on_text(update, context)

    assert [m.text for m in update.sent] == ["Hello there!"]
    assert await store.get_history(42) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello there!"},
    ]
    context.bot.send_chat_action.assert_awaited()


async def test_history_is_sent_to_llm_as_context(build_handlers, context, store):
    llm = FakeLLM("second answer")
    handlers = build_handlers(llm, stream_replies=False)
    await store.append_exchange(42, "first question", "first answer")

    await handlers.on_text(make_update("second question"), context)

    assert [m["content"] for m in llm.calls[0]] == [
        "first question",
        "first answer",
        "second question",
    ]


async def test_long_reply_is_split_across_messages(build_handlers, context):
    reply = "word " * 2000
    handlers = build_handlers(FakeLLM(reply), stream_replies=False)
    update = make_update()

    await handlers.on_text(update, context)

    assert len(update.sent) == 3
    assert all(len(m.text) <= TELEGRAM_MAX_LENGTH for m in update.sent)


async def test_llm_error_shows_friendly_message_and_stores_nothing(build_handlers, context, store):
    handlers = build_handlers(FakeLLM(error=LLMError("Try later")), stream_replies=False)
    update = make_update()

    await handlers.on_text(update, context)

    assert [m.text for m in update.sent] == ["Try later"]
    assert await store.get_history(42) == []


async def test_rate_limited_user_gets_notice_without_llm_call(build_handlers, context):
    llm = FakeLLM()
    handlers = build_handlers(llm, stream_replies=False, rate_limit_messages=1)

    await handlers.on_text(make_update(), context)
    blocked = make_update()
    await handlers.on_text(blocked, context)

    assert len(llm.calls) == 1
    assert "too quickly" in blocked.sent[0].text


async def test_streaming_edits_single_message_into_final_reply(build_handlers, context, store):
    handlers = build_handlers(FakeLLM("one two three"), stream_replies=True)
    update = make_update()

    await handlers.on_text(update, context)

    assert len(update.sent) == 1
    message = update.sent[0]
    assert message.text == "one two three"
    assert any(edit.endswith(STREAM_CURSOR) for edit in message.edits)
    assert (await store.get_history(42))[-1]["content"] == "one two three"


async def test_streaming_long_reply_overflows_into_follow_up_messages(build_handlers, context):
    handlers = build_handlers(FakeLLM("word " * 2000), stream_replies=True)
    update = make_update()

    await handlers.on_text(update, context)

    assert len(update.sent) == 3
    assert all(len(m.text) <= TELEGRAM_MAX_LENGTH for m in update.sent)
    assert not update.sent[0].text.endswith(STREAM_CURSOR)


async def test_stream_failure_marks_partial_reply_and_reports_error(build_handlers, context, store):
    handlers = build_handlers(FakeLLM("partial text", error=LLMError("Oops")), stream_replies=True)
    update = make_update()

    await handlers.on_text(update, context)

    assert update.sent[0].text.endswith(INTERRUPTED_SUFFIX)
    assert update.sent[-1].text == "Oops"
    assert await store.get_history(42) == []


async def test_reset_clears_history(build_handlers, context, store):
    handlers = build_handlers()
    await store.append_exchange(42, "q", "a")
    update = make_update("/reset")

    await handlers.reset(update, context)

    assert await store.get_history(42) == []
    assert update.sent[0].text == RESET_TEXT


async def test_updates_without_message_are_ignored(build_handlers, context):
    llm = FakeLLM()
    handlers = build_handlers(llm)
    update = make_update()
    update.effective_message = None  # e.g. an edited message or channel post

    await handlers.on_text(update, context)

    assert llm.calls == []


async def test_error_handler_apologises(build_handlers, monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply_text", reply)
    message = Message(1, datetime.now(UTC), Chat(42, Chat.PRIVATE), text="hi")
    context = SimpleNamespace(error=RuntimeError("boom"))

    await build_handlers().on_error(Update(update_id=1, message=message), context)

    reply.assert_awaited_once_with(GENERIC_ERROR_TEXT)
