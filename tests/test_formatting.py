from bot.formatting import TELEGRAM_MAX_LENGTH, split_message


def test_short_text_is_single_chunk():
    assert split_message("  hello  ") == ["hello"]


def test_empty_text_yields_no_chunks():
    assert split_message("   ") == []


def test_long_text_chunks_respect_limit_and_preserve_words():
    text = " ".join(f"word{i}" for i in range(3000))
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= TELEGRAM_MAX_LENGTH for chunk in chunks)
    assert " ".join(chunks).split() == text.split()


def test_prefers_paragraph_boundaries():
    first, second = "a" * 60, "b" * 60
    assert split_message(f"{first}\n\n{second}", limit=100) == [first, second]


def test_hard_cut_when_no_separator_available():
    chunks = split_message("x" * 250, limit=100)
    assert chunks == ["x" * 100, "x" * 100, "x" * 50]
