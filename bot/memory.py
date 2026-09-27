"""Conversation memory: persistent per-chat history and context-window trimming."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import TypedDict


class ChatMessage(TypedDict):
    role: str
    content: str


# Rough OpenAI-style estimate (~4 characters per token) plus per-message overhead.
# Precise enough for budgeting a context window without pulling in a tokenizer.
_CHARS_PER_TOKEN = 4
_MESSAGE_OVERHEAD_TOKENS = 4


def estimate_tokens(message: ChatMessage) -> int:
    return len(message["content"]) // _CHARS_PER_TOKEN + _MESSAGE_OVERHEAD_TOKENS


def trim_to_budget(messages: list[ChatMessage], max_tokens: int) -> list[ChatMessage]:
    """Return the most recent messages that fit within ``max_tokens``.

    The newest message is always kept, even if it alone exceeds the budget,
    so the user's current question is never dropped.
    """
    kept: list[ChatMessage] = []
    used = 0
    for message in reversed(messages):
        cost = estimate_tokens(message)
        if kept and used + cost > max_tokens:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    return kept


class ConversationStore:
    """SQLite-backed chat history.

    ``sqlite3`` is blocking, so every call runs in a worker thread via
    :func:`asyncio.to_thread` to keep the bot's event loop responsive. A single
    connection guarded by a lock is ample for a bot's write volume.
    """

    def __init__(self, path: str | Path, max_messages_per_chat: int = 50) -> None:
        self.max_messages_per_chat = max_messages_per_chat
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    role       TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
                    content    TEXT    NOT NULL,
                    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id)"
            )

    async def get_history(self, chat_id: int) -> list[ChatMessage]:
        return await asyncio.to_thread(self._get_history, chat_id)

    async def append_exchange(self, chat_id: int, user_text: str, assistant_text: str) -> None:
        """Store a user message and the bot's reply atomically."""
        await asyncio.to_thread(self._append_exchange, chat_id, user_text, assistant_text)

    async def reset(self, chat_id: int) -> None:
        await asyncio.to_thread(self._reset, chat_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _get_history(self, chat_id: int) -> list[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id",
                (chat_id,),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    def _append_exchange(self, chat_id: int, user_text: str, assistant_text: str) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                [(chat_id, "user", user_text), (chat_id, "assistant", assistant_text)],
            )
            # Keep storage bounded: drop everything but the newest N messages.
            self._conn.execute(
                """
                DELETE FROM messages
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (chat_id, chat_id, self.max_messages_per_chat),
            )

    def _reset(self, chat_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))


class ChatLocks:
    """One :class:`asyncio.Lock` per chat.

    Updates are processed concurrently across chats, but messages within a
    chat are handled in order so history is never interleaved or overwritten.
    """

    def __init__(self) -> None:
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __call__(self, chat_id: int) -> asyncio.Lock:
        return self._locks[chat_id]
