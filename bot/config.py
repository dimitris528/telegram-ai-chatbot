"""Typed runtime configuration, loaded from environment variables.

All settings are validated once at startup so that a misconfigured deployment
fails immediately with a clear message instead of on the first user message.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise assistant chatting with a user on Telegram. "
    "Answer clearly, prefer short paragraphs and plain text, and reply in the "
    "same language the user writes in."
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Raised when required settings are missing or malformed."""


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    openai_timeout: float = 30.0
    openai_max_retries: int = 2
    max_history_tokens: int = 3000
    max_stored_messages: int = 50
    rate_limit_messages: int = 10
    rate_limit_window_seconds: float = 60.0
    stream_replies: bool = True
    stream_edit_interval: float = 1.0
    db_path: str = "data/conversations.db"
    log_level: str = "INFO"
    webhook_url: str | None = None
    webhook_port: int = 8080
    webhook_secret: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        errors: list[str] = []

        def get(name: str, default: str | None = None) -> str | None:
            value = env.get(name, "").strip()
            return value or default

        def required(name: str) -> str:
            value = get(name)
            if value is None:
                errors.append(f"{name} is required")
                return ""
            return value

        def number(name: str, default: float, cast: type, minimum: float) -> float:
            raw = get(name)
            if raw is None:
                return default
            try:
                value = cast(raw)
            except ValueError:
                errors.append(f"{name} must be a number, got {raw!r}")
                return default
            if value < minimum:
                errors.append(f"{name} must be >= {minimum}, got {value}")
            return value

        def boolean(name: str, default: bool) -> bool:
            raw = get(name)
            if raw is None:
                return default
            if raw.lower() in _TRUE:
                return True
            if raw.lower() in _FALSE:
                return False
            errors.append(f"{name} must be true/false, got {raw!r}")
            return default

        settings = cls(
            telegram_token=required("TELEGRAM_TOKEN"),
            openai_api_key=required("OPENAI_API_KEY"),
            openai_model=get("OPENAI_MODEL", cls.openai_model),
            system_prompt=get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
            openai_timeout=number("OPENAI_TIMEOUT", cls.openai_timeout, float, 1),
            openai_max_retries=number("OPENAI_MAX_RETRIES", cls.openai_max_retries, int, 0),
            max_history_tokens=number("MAX_HISTORY_TOKENS", cls.max_history_tokens, int, 100),
            max_stored_messages=number("MAX_STORED_MESSAGES", cls.max_stored_messages, int, 2),
            rate_limit_messages=number("RATE_LIMIT_MESSAGES", cls.rate_limit_messages, int, 1),
            rate_limit_window_seconds=number(
                "RATE_LIMIT_WINDOW_SECONDS", cls.rate_limit_window_seconds, float, 1
            ),
            stream_replies=boolean("STREAM_REPLIES", cls.stream_replies),
            stream_edit_interval=number(
                "STREAM_EDIT_INTERVAL", cls.stream_edit_interval, float, 0.3
            ),
            db_path=get("DB_PATH", cls.db_path),
            log_level=get("LOG_LEVEL", cls.log_level).upper(),
            webhook_url=get("WEBHOOK_URL"),
            webhook_port=number("PORT", cls.webhook_port, int, 1),
            webhook_secret=get("WEBHOOK_SECRET"),
        )

        if errors:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))
        return settings
