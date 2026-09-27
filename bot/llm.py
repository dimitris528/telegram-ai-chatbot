"""OpenAI chat-completions client with streaming and user-safe error mapping."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from bot.config import Settings
from bot.memory import ChatMessage

logger = logging.getLogger(__name__)

EMPTY_REPLY_FALLBACK = "I don't have a response to that. Could you rephrase?"


class LLMError(Exception):
    """An LLM failure carrying a message that is safe to show the end user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


def _to_llm_error(exc: openai.APIError) -> LLMError:
    """Translate provider exceptions into friendly, non-leaky user messages."""
    if isinstance(exc, openai.APITimeoutError):
        return LLMError("The AI service took too long to respond. Please try again.")
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("I couldn't reach the AI service. Please try again in a moment.")
    if isinstance(exc, openai.RateLimitError):
        return LLMError("I'm handling a lot of requests right now. Please try again shortly.")
    if isinstance(exc, openai.BadRequestError) and exc.code == "context_length_exceeded":
        return LLMError("This conversation has grown too long. Send /reset to start fresh.")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        logger.critical("OpenAI rejected the API key; check OPENAI_API_KEY")
    return LLMError("Sorry, something went wrong on my side. Please try again.")


class LLMClient:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self.model = settings.openai_model
        self.system_prompt = settings.system_prompt
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout,
            max_retries=settings.openai_max_retries,
        )

    def build_messages(self, conversation: list[ChatMessage]) -> list[ChatMessage]:
        return [{"role": "system", "content": self.system_prompt}, *conversation]

    async def complete(self, conversation: list[ChatMessage]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self.model, messages=self.build_messages(conversation)
            )
        except openai.APIError as exc:
            logger.warning("OpenAI request failed: %s", type(exc).__name__)
            raise _to_llm_error(exc) from exc

        content = response.choices[0].message.content if response.choices else None
        return content.strip() if content and content.strip() else EMPTY_REPLY_FALLBACK

    async def stream(self, conversation: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield text deltas as the model generates them."""
        try:
            stream = await self._client.chat.completions.create(
                model=self.model, messages=self.build_messages(conversation), stream=True
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except openai.APIError as exc:
            logger.warning("OpenAI stream failed: %s", type(exc).__name__)
            raise _to_llm_error(exc) from exc

    async def close(self) -> None:
        await self._client.close()
