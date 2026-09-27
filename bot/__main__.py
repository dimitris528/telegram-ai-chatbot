"""Entry point: ``python -m bot``."""

from __future__ import annotations

import sys

from dotenv import find_dotenv, load_dotenv
from telegram import Update

from bot.app import build_application, configure_logging
from bot.config import ConfigError, Settings


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)

    configure_logging(settings.log_level)
    app = build_application(settings)

    if settings.webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=settings.webhook_port,
            url_path="telegram",
            webhook_url=f"{settings.webhook_url.rstrip('/')}/telegram",
            secret_token=settings.webhook_secret,
            allowed_updates=[Update.MESSAGE],
            drop_pending_updates=True,
        )
    else:
        app.run_polling(allowed_updates=[Update.MESSAGE], drop_pending_updates=True)


if __name__ == "__main__":
    main()
