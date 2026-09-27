"""Telegram update handlers: commands, chat messages, and global error handling."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from telegram import Bot, Message, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import Settings
from bot.formatting import TELEGRAM_MAX_LENGTH, split_message
from bot.llm import EMPTY_REPLY_FALLBACK, LLMClient, LLMError
from bot.memory import ChatLocks, ChatMessage, ConversationStore, trim_to_budget
from bot.ratelimit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Hi! I'm an AI assistant. Send me a message and I'll reply, remembering the "
    "context of our conversation.\n\n"
    "/reset - forget our conversation and start fresh\n"
    "/help - show this message"
)
RESET_TEXT = "Done. I've cleared our conversation history."
GENERIC_ERROR_TEXT = "Sorry, something went wrong. Please try again."
STREAM_CURSOR = " ▌"
INTERRUPTED_SUFFIX = "\n\n[response interrupted]"
TYPING_REFRESH_SECONDS = 4.0  # Telegram clears the typing status after ~5s.


class BotHandlers:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        store: ConversationStore,
        limiter: SlidingWindowRateLimiter,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.store = store
        self.limiter = limiter
        self.locks = ChatLocks()
        self._clock = clock

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler(["start", "help"], self.start))
        app.add_handler(CommandHandler("reset", self.reset))
        app.add_handler(
            MessageHandler(
                filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, self.on_text
            )
        )
        app.add_error_handler(self.on_error)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(WELCOME_TEXT)

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_message is None:
            return
        async with self.locks(update.effective_chat.id):
            await self.store.reset(update.effective_chat.id)
        await update.effective_message.reply_text(RESET_TEXT)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, chat = update.effective_message, update.effective_chat
        if message is None or chat is None or not message.text:
            return

        user_key = update.effective_user.id if update.effective_user else chat.id
        retry_in = self.limiter.check(user_key)
        if retry_in > 0:
            await message.reply_text(
                f"You're sending messages too quickly. Please wait {math.ceil(retry_in)}s."
            )
            return

        async with self.locks(chat.id):
            history = await self.store.get_history(chat.id)
            conversation = trim_to_budget(
                [*history, {"role": "user", "content": message.text}],
                self.settings.max_history_tokens,
            )
            started = self._clock()
            try:
                if self.settings.stream_replies:
                    reply = await self._stream_reply(message, conversation, context.bot)
                else:
                    reply = await self._complete_reply(message, conversation, context.bot)
            except LLMError as exc:
                await message.reply_text(exc.user_message)
                return

            await self.store.append_exchange(chat.id, message.text, reply)

        # Log metadata only; message contents are user data and stay out of logs.
        logger.info(
            "Replied chat_id=%s context_msgs=%d reply_chars=%d latency=%.2fs",
            chat.id,
            len(conversation),
            len(reply),
            self._clock() - started,
        )

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Unhandled error while processing update", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            with suppress(TelegramError):
                await update.effective_message.reply_text(GENERIC_ERROR_TEXT)

    async def _complete_reply(
        self, message: Message, conversation: list[ChatMessage], bot: Bot
    ) -> str:
        async with _typing(bot, message.chat_id):
            reply = await self.llm.complete(conversation)
        for chunk in split_message(reply):
            await message.reply_text(chunk)
        return reply

    async def _stream_reply(
        self, message: Message, conversation: list[ChatMessage], bot: Bot
    ) -> str:
        """Stream tokens into a single Telegram message via throttled edits.

        Telegram has no native token streaming, so the reply is sent once text
        is available and then edited at most every ``stream_edit_interval``
        seconds to stay clear of Telegram's flood limits. Replies longer than
        one message are split into follow-up messages when the stream ends.
        """
        preview_limit = TELEGRAM_MAX_LENGTH - len(STREAM_CURSOR)
        text = ""
        shown = ""
        sent: Message | None = None
        last_edit = 0.0

        async with _typing(bot, message.chat_id):
            try:
                async for delta in self.llm.stream(conversation):
                    text += delta
                    preview = text[:preview_limit].strip()
                    if not preview or preview == shown:
                        continue
                    now = self._clock()
                    if sent is None:
                        sent = await message.reply_text(preview + STREAM_CURSOR)
                    elif now - last_edit >= self.settings.stream_edit_interval:
                        await _edit(sent, preview + STREAM_CURSOR)
                    else:
                        continue
                    shown, last_edit = preview, now
            except LLMError:
                if sent is not None:
                    partial = text[: TELEGRAM_MAX_LENGTH - len(INTERRUPTED_SUFFIX)].strip()
                    await _edit(sent, partial + INTERRUPTED_SUFFIX)
                raise

        reply = text.strip() or EMPTY_REPLY_FALLBACK
        chunks = split_message(reply)
        if sent is None or not await _edit(sent, chunks[0], final=True):
            await message.reply_text(chunks[0])
        for chunk in chunks[1:]:
            await message.reply_text(chunk)
        return reply


async def _edit(message: Message, text: str, final: bool = False) -> bool:
    """Edit ``message`` best-effort; returns whether it now shows ``text``.

    Intermediate streaming edits are simply skipped when throttled. The final
    edit waits out one flood-control delay so the complete reply lands.
    """
    for attempt in range(2 if final else 1):
        try:
            await message.edit_text(text)
            return True
        except RetryAfter as exc:
            if not final or attempt == 1:
                return False
            await asyncio.sleep(min(_seconds(exc.retry_after), 30.0))
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return True
            logger.debug("Edit failed: %s", exc)
            return False
    return False


def _seconds(value: int | float | timedelta) -> float:
    return value.total_seconds() if isinstance(value, timedelta) else float(value)


@asynccontextmanager
async def _typing(bot: Bot, chat_id: int) -> AsyncIterator[None]:
    """Show the "typing..." indicator until the block exits."""

    async def send_typing() -> None:
        with suppress(TelegramError):
            await bot.send_chat_action(chat_id, ChatAction.TYPING)

    async def keep_typing() -> None:
        while True:
            await asyncio.sleep(TYPING_REFRESH_SECONDS)
            await send_typing()

    await send_typing()
    task = asyncio.create_task(keep_typing())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
