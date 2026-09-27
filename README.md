# Telegram AI Chatbot

[![CI](https://github.com/dimitris528/telegram-ai-chatbot/actions/workflows/ci.yml/badge.svg)](https://github.com/dimitris528/telegram-ai-chatbot/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.x-26A5E4?logo=telegram&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-Chat%20Completions-412991?logo=openai&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-memory-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Ruff](https://img.shields.io/badge/code%20style-ruff-D7FF64?logo=ruff&logoColor=black)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A production-ready conversational AI assistant for Telegram. It remembers the
context of each conversation, streams answers token by token, and degrades
gracefully when the LLM provider is slow or unavailable. It's built fully async
on `python-telegram-bot` and the OpenAI API.

## Overview

Teams increasingly want AI assistants to live where users already are, rather than
behind yet another web app. Telegram is a natural fit: it has a first-class bot API,
it works on every device, and it needs no onboarding. However, a naive
"forward the message to the LLM" bot quickly runs into problems:

- **It forgets everything** between messages, or grows its prompt without bound until requests fail.
- **It blocks.** A synchronous LLM call inside an async bot freezes every user while one request is in flight.
- **It breaks on real output.** Telegram rejects messages over 4,096 characters, and long answers simply disappear.
- **It fails opaquely.** Timeouts, rate limits, and provider outages surface as silence or stack traces.
- **It's an open wallet.** A single user can flood the bot and run up the API bill.

This project solves each of these problems with a small, clearly layered, fully
tested service that can be deployed with Docker, Render, or systemd in minutes.
The same architecture is the foundation for workflow automation bots: support
triage, internal knowledge assistants, and lead qualification.

## Architecture

```
                         ┌──────────────────────────────────────────────────────────┐
  ┌──────────────┐       │                        Bot Service                       │
  │   Telegram   │       │                                                          │
  │    users     │       │  ┌───────────────┐   ┌──────────────┐   ┌──────────────┐ │
  └──────┬───────┘       │  │   Handlers    │──▶│ Rate limiter │   │   Settings   │ │
         │               │  │ /start /help  │   │ sliding win. │   │ env, fail-   │ │
         ▼               │  │ /reset, text, │   │  per user    │   │ fast checks  │ │
  ┌──────────────┐ poll  │  │ error handler │   └──────────────┘   └──────────────┘ │
  │ Telegram Bot │◀─────▶│  └──────┬────────┘                                       │
  │     API      │  or   │         │ per-chat asyncio.Lock (ordered, no races)      │
  └──────────────┘webhook│         ▼                                                │
         ▲               │  ┌───────────────┐  history   ┌───────────────────────┐  │
         │               │  │ Context Memory│◀──────────▶│ SQLite (WAL)          │  │
         │               │  │ token-budget  │  append /  │ bounded per-chat log  │  │
         │               │  │ window trim   │  prune     └───────────────────────┘  │
         │               │  └──────┬────────┘                                       │
         │               │         │ system prompt + trimmed history                │
         │               │         ▼                                                │
         │               │  ┌───────────────┐  stream   ┌───────────────────────┐   │
         │  throttled    │  │  LLM Client   │◀─────────▶│ OpenAI API            │   │
         └── edits / ────┼──│ AsyncOpenAI,  │  tokens   │ (gpt-4o-mini default) │   │
             chunked     │  │ timeout/retry │           └───────────────────────┘   │
             replies     │  │ error mapping │                                       │
                         │  └───────────────┘                                       │
                         └──────────────────────────────────────────────────────────┘
```

**Request lifecycle**

1. An update arrives via **long polling** (the default) or a **webhook** (when `WEBHOOK_URL` is set).
2. The **rate limiter** checks the sender's sliding window. If the sender is over the limit, they get a polite retry hint and no LLM call is made.
3. A **per-chat lock** serializes messages within one conversation, while different chats are processed concurrently.
4. **Context memory** loads the chat's history from SQLite, appends the new message, and trims the oldest turns to fit the token budget.
5. The **LLM client** prepends the system prompt and streams the completion.
6. The handler **streams the reply into Telegram**, splitting it across messages if it exceeds 4,096 characters.
7. Only when the reply succeeds is the user/assistant exchange **persisted atomically**. Older messages are then pruned.

## Key technical highlights

| Area | What it does | Where |
|---|---|---|
| **Context retention** | Per-chat history lives in SQLite. The context window is trimmed by an approximate **token budget** rather than a fixed message count, and the newest message is always kept. Storage per chat is bounded. | `bot/memory.py` |
| **Token streaming** | Telegram has no native token streaming. Instead, the reply is sent as soon as text exists and then **edited at a throttled interval** with a `▌` cursor, which stays clear of Telegram flood limits. `RetryAfter` is handled on the final edit. | `bot/handlers.py` |
| **Chunking** | Long answers are split on paragraph, then line, sentence, and word boundaries, and only hard-cut as a last resort. Every message stays within Telegram's 4,096-character limit. | `bot/formatting.py` |
| **Prompt engineering** | A configurable system prompt (`SYSTEM_PROMPT`) is injected on every request. The default tunes the model for concise, plain-text chat that mirrors the user's language. | `bot/config.py`, `bot/llm.py` |
| **Graceful error fallbacks** | Provider errors (timeouts, connection failures, rate limits, context overflow, auth) map to **user-safe messages** that never leak internals. An interrupted stream is marked as such. A global error handler catches everything else. | `bot/llm.py`, `bot/handlers.py` |
| **Async correctness** | `AsyncOpenAI` means the event loop never blocks. Blocking SQLite I/O runs in worker threads. Updates are processed concurrently across chats, with per-chat locks to prevent history races. | `bot/app.py`, `bot/memory.py` |
| **Abuse & cost control** | A per-user sliding-window rate limiter, request timeouts, bounded retries, and bounded history protect both the API budget and the service. | `bot/ratelimit.py` |
| **Security & privacy** | Configuration is validated at startup (fail fast). Secrets come only from the environment. Logs record **metadata only**, never message contents. The `httpx` request logs, which embed the bot token in URLs, are silenced. Webhooks support Telegram's secret-token verification. | `bot/config.py`, `bot/app.py` |
| **Tested without network** | A pytest suite with fakes for OpenAI and Telegram covers config, chunking, memory, rate limiting, error mapping, streaming, and app wiring. | `tests/` |

## Project structure

```
bot/
├── __main__.py     # Entry point: python -m bot (polling or webhook)
├── app.py          # Application assembly, lifecycle hooks, logging
├── config.py       # Typed, validated settings from environment variables
├── handlers.py     # Commands, chat handler, streaming, error handler
├── llm.py          # AsyncOpenAI client, streaming, error mapping
├── memory.py       # SQLite conversation store, token-budget trimming, chat locks
├── ratelimit.py    # Per-user sliding-window rate limiter
└── formatting.py   # Telegram-safe message chunking
tests/              # pytest suite (no network, no credentials required)
deploy/             # systemd unit
Dockerfile          # Slim, non-root production image
render.yaml         # Render Blueprint (Background Worker)
```

## Bot commands

| Command | Description |
|---|---|
| `/start`, `/help` | Introduction and usage |
| `/reset` | Forget the current conversation and start fresh |

## Local setup

**Prerequisites:** Python 3.11 or later, a bot token from [@BotFather](https://t.me/BotFather), and an [OpenAI API key](https://platform.openai.com/api-keys).

```bash
git clone https://github.com/dimitris528/telegram-ai-chatbot.git
cd telegram-ai-chatbot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # then fill in TELEGRAM_TOKEN and OPENAI_API_KEY
python -m bot
```

Open your bot in Telegram and send it a message.

### Run tests & linting

```bash
pytest
ruff check . && ruff format --check .
```

## Configuration

Settings are read from environment variables, or from a `.env` file in the working directory.
See [`.env.example`](.env.example) for a documented template.

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | **required** | Bot token from @BotFather |
| `OPENAI_API_KEY` | **required** | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model to use |
| `SYSTEM_PROMPT` | concise-assistant prompt | System instructions sent with every request |
| `OPENAI_TIMEOUT` | `30` | Seconds before an LLM request is abandoned |
| `OPENAI_MAX_RETRIES` | `2` | Automatic retries on transient provider errors |
| `MAX_HISTORY_TOKENS` | `3000` | Approximate token budget for history sent to the model |
| `MAX_STORED_MESSAGES` | `50` | Messages retained per chat in the database |
| `DB_PATH` | `data/conversations.db` | SQLite database location |
| `RATE_LIMIT_MESSAGES` | `10` | Messages allowed per user per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate-limit window length |
| `STREAM_REPLIES` | `true` | Stream tokens via message edits (`false` sends the complete reply at once) |
| `STREAM_EDIT_INTERVAL` | `1.0` | Minimum seconds between streaming edits |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `WEBHOOK_URL` | *(empty)* | Public HTTPS base URL. When set, the bot uses webhook mode instead of polling |
| `PORT` | `8080` | Port for the webhook server |
| `WEBHOOK_SECRET` | *(empty)* | Secret token Telegram sends with each webhook request |

Invalid or missing values stop the bot at startup with exit code `2` and a list of every problem found.

## Deployment

> Run **exactly one** polling instance per bot token. Telegram rejects concurrent
> `getUpdates` calls. The rate limiter and chat locks are in-process, so scaling
> horizontally would require webhook mode plus a shared store such as Redis.

### Docker

```bash
docker build -t telegram-ai-chatbot .
docker run -d --name telegram-ai-chatbot --restart unless-stopped \
  --env-file .env \
  -v telegram-bot-data:/app/data \
  telegram-ai-chatbot
```

The image runs as a non-root user. Conversation history is stored in the
`/app/data` volume, so it survives container restarts and upgrades.

### Render

The repo includes a [Render Blueprint](render.yaml) that deploys the bot as a
**Background Worker**. Long polling needs no public URL.

1. In Render, choose **New → Blueprint** and select this repository.
2. Set `TELEGRAM_TOKEN` and `OPENAI_API_KEY` when prompted.
3. Deploy. The persistent disk keeps history across deploys. Without a disk the bot
   still works, but history resets on each deploy.

### systemd (Linux VM)

```bash
sudo useradd --system --home /opt/telegram-ai-chatbot telegram-bot
sudo git clone https://github.com/dimitris528/telegram-ai-chatbot.git /opt/telegram-ai-chatbot
cd /opt/telegram-ai-chatbot
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env      # add your credentials
sudo chown root:telegram-bot .env && sudo chmod 640 .env

sudo cp deploy/telegram-ai-chatbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-ai-chatbot
journalctl -u telegram-ai-chatbot -f
```

The unit runs under a dedicated user with systemd sandboxing (`ProtectSystem=strict`,
`NoNewPrivileges`, and so on) and stores its database in `/var/lib/telegram-ai-chatbot`.

### Webhook mode

For platforms that route HTTPS traffic to your service, set `WEBHOOK_URL`
(for example `https://bot.example.com`), `PORT`, and a random `WEBHOOK_SECRET`.
The bot registers `https://bot.example.com/telegram` with Telegram and rejects
requests that lack the secret header.

## Roadmap

- Pluggable LLM providers (Anthropic Claude, local models) behind the `LLMClient` interface
- Tool/function calling for workflow automation (CRM lookups, ticket creation)
- Redis-backed rate limiting and memory for multi-replica deployments
- Conversation summarization to retain long-range context within the token budget

## License

[MIT](LICENSE)
