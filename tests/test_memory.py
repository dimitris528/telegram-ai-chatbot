from bot.memory import ConversationStore, estimate_tokens, trim_to_budget


def msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_trim_keeps_newest_messages_within_budget():
    messages = [msg("user", "x" * 400) for _ in range(10)]  # ~104 tokens each
    trimmed = trim_to_budget(messages, max_tokens=250)
    assert trimmed == messages[-2:]
    assert sum(estimate_tokens(m) for m in trimmed) <= 250


def test_trim_always_keeps_latest_message():
    huge = msg("user", "x" * 100_000)
    assert trim_to_budget([msg("user", "old"), huge], max_tokens=10) == [huge]


def test_trim_preserves_order():
    messages = [msg("user", "a"), msg("assistant", "b"), msg("user", "c")]
    assert trim_to_budget(messages, max_tokens=1000) == messages


async def test_store_roundtrip_and_chat_isolation(store):
    await store.append_exchange(1, "hi", "hello")
    await store.append_exchange(2, "other", "chat")
    assert await store.get_history(1) == [msg("user", "hi"), msg("assistant", "hello")]
    assert len(await store.get_history(2)) == 2


async def test_store_reset_only_affects_one_chat(store):
    await store.append_exchange(1, "hi", "hello")
    await store.append_exchange(2, "hi", "hello")
    await store.reset(1)
    assert await store.get_history(1) == []
    assert len(await store.get_history(2)) == 2


async def test_store_prunes_to_max_messages():
    store = ConversationStore(":memory:", max_messages_per_chat=4)
    for i in range(5):
        await store.append_exchange(1, f"q{i}", f"a{i}")
    history = await store.get_history(1)
    assert [m["content"] for m in history] == ["q3", "a3", "q4", "a4"]
    store.close()


async def test_store_persists_to_disk(tmp_path):
    path = tmp_path / "nested" / "chat.db"
    first = ConversationStore(path)
    await first.append_exchange(1, "γεια", "hello")  # non-ASCII survives
    first.close()

    second = ConversationStore(path)
    assert await second.get_history(1) == [msg("user", "γεια"), msg("assistant", "hello")]
    second.close()
