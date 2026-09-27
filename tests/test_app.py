"""Smoke test: the full application wires up without network access."""

from telegram.ext import CommandHandler, MessageHandler

from bot.app import build_application
from tests.conftest import make_settings


def test_build_application_registers_handlers():
    app = build_application(make_settings())

    handlers = app.handlers[0]
    commands = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
    assert commands == {"start", "help", "reset"}
    assert any(isinstance(h, MessageHandler) for h in handlers)
    assert app.error_handlers
    assert app.concurrent_updates
