"""Application assembly: wires settings, services, and handlers together."""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder

from bot.config import Settings
from bot.handlers import BotHandlers
from bot.llm import LLMClient
from bot.memory import ConversationStore
from bot.ratelimit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("start", "Introduction and usage"),
    BotCommand("help", "Show available commands"),
    BotCommand("reset", "Forget the conversation and start fresh"),
]


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=level,
    )
    # httpx logs every request URL at INFO, and Telegram URLs embed the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)


def build_application(settings: Settings) -> Application:
    store = ConversationStore(settings.db_path, settings.max_stored_messages)
    llm = LLMClient(settings)
    limiter = SlidingWindowRateLimiter(
        settings.rate_limit_messages, settings.rate_limit_window_seconds
    )
    handlers = BotHandlers(settings, llm, store, limiter)

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands(BOT_COMMANDS)
        logger.info("Bot @%s ready (model=%s)", app.bot.username, settings.openai_model)

    async def post_shutdown(app: Application) -> None:
        await llm.close()
        store.close()
        logger.info("Shutdown complete")

    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        # Handle different chats in parallel; per-chat locks keep each chat ordered.
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    handlers.register(app)
    return app
