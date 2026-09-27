from types import SimpleNamespace

import httpx2
import openai
import pytest

from bot.llm import EMPTY_REPLY_FALLBACK, LLMError

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def stream_chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


async def async_iter(items):
    for item in items:
        yield item


def status_error(cls, status: int, body=None):
    return cls("error", response=httpx2.Response(status, request=REQUEST), body=body)


async def test_complete_prepends_system_prompt(llm_client, fake_openai):
    fake_openai.chat.completions.create.return_value = completion("  Hi!  ")
    reply = await llm_client.complete([{"role": "user", "content": "hello"}])

    assert reply == "Hi!"
    sent = fake_openai.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "SYSTEM"}
    assert sent[1] == {"role": "user", "content": "hello"}


@pytest.mark.parametrize("content", [None, "", "   "])
async def test_complete_falls_back_on_empty_content(llm_client, fake_openai, content):
    fake_openai.chat.completions.create.return_value = completion(content)
    assert await llm_client.complete([]) == EMPTY_REPLY_FALLBACK


async def test_stream_yields_non_empty_deltas(llm_client, fake_openai):
    chunks = [stream_chunk("Hel"), stream_chunk(None), stream_chunk("lo")]
    fake_openai.chat.completions.create.return_value = async_iter(chunks)
    assert [d async for d in llm_client.stream([])] == ["Hel", "lo"]
    assert fake_openai.chat.completions.create.call_args.kwargs["stream"] is True


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (openai.APITimeoutError(request=REQUEST), "too long"),
        (openai.APIConnectionError(request=REQUEST), "couldn't reach"),
        (status_error(openai.RateLimitError, 429), "lot of requests"),
        (
            status_error(openai.BadRequestError, 400, {"code": "context_length_exceeded"}),
            "/reset",
        ),
        (status_error(openai.AuthenticationError, 401), "something went wrong"),
        (status_error(openai.InternalServerError, 500), "something went wrong"),
    ],
)
async def test_provider_errors_map_to_friendly_messages(llm_client, fake_openai, error, expected):
    fake_openai.chat.completions.create.side_effect = error
    with pytest.raises(LLMError) as info:
        await llm_client.complete([])
    assert expected in info.value.user_message
    assert "sk-" not in info.value.user_message


async def test_stream_errors_are_mapped_too(llm_client, fake_openai):
    fake_openai.chat.completions.create.side_effect = status_error(openai.RateLimitError, 429)
    with pytest.raises(LLMError):
        async for _ in llm_client.stream([]):
            pass
