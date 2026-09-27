import pytest

from bot.config import DEFAULT_SYSTEM_PROMPT, ConfigError, Settings

REQUIRED = {"TELEGRAM_TOKEN": "123:abc", "OPENAI_API_KEY": "sk-test"}


def test_defaults_applied_when_only_required_vars_set():
    settings = Settings.from_env(REQUIRED)
    assert settings.telegram_token == "123:abc"
    assert settings.openai_model == "gpt-4o-mini"
    assert settings.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert settings.stream_replies is True
    assert settings.webhook_url is None


def test_missing_required_vars_are_all_reported():
    with pytest.raises(ConfigError) as info:
        Settings.from_env({})
    assert "TELEGRAM_TOKEN" in str(info.value)
    assert "OPENAI_API_KEY" in str(info.value)


def test_blank_values_count_as_missing():
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Settings.from_env({"TELEGRAM_TOKEN": "x", "OPENAI_API_KEY": "   "})


def test_overrides_are_parsed_and_typed():
    settings = Settings.from_env(
        {
            **REQUIRED,
            "OPENAI_MODEL": "gpt-4.1-mini",
            "MAX_HISTORY_TOKENS": "1500",
            "RATE_LIMIT_WINDOW_SECONDS": "30.5",
            "STREAM_REPLIES": "false",
            "LOG_LEVEL": "debug",
            "PORT": "9000",
        }
    )
    assert settings.openai_model == "gpt-4.1-mini"
    assert settings.max_history_tokens == 1500
    assert settings.rate_limit_window_seconds == 30.5
    assert settings.stream_replies is False
    assert settings.log_level == "DEBUG"
    assert settings.webhook_port == 9000


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_HISTORY_TOKENS", "lots"),
        ("MAX_HISTORY_TOKENS", "5"),
        ("STREAM_REPLIES", "maybe"),
        ("OPENAI_TIMEOUT", "0"),
    ],
)
def test_invalid_values_are_rejected(name, value):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env({**REQUIRED, name: value})
