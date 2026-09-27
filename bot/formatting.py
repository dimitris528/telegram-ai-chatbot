"""Helpers for fitting LLM output into Telegram's message size limit."""

from __future__ import annotations

from telegram.constants import MessageLimit

TELEGRAM_MAX_LENGTH = MessageLimit.MAX_TEXT_LENGTH  # 4096 characters

# Preferred break points, from most to least natural.
_SEPARATORS = ("\n\n", "\n", ". ", " ")


def split_message(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters.

    Breaks on paragraph, line, sentence, then word boundaries, and only falls
    back to a hard cut when a single token is longer than ``limit``.
    """
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = -1
        for separator in _SEPARATORS:
            index = window.rfind(separator)
            # Ignore breaks that would leave a uselessly small first chunk.
            if index > limit // 4:
                cut = index + len(separator)
                break
        if cut == -1:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)
    return chunks
