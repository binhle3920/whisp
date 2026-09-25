# Getting started

This guide runs Whisp locally and verifies the complete Gmail-to-Telegram workflow.

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- A Gmail account
- An OpenRouter account with API credits
- A Telegram account

Docker is optional and is useful after the first local setup succeeds.

## Install Whisp

Clone the repository, enter its directory, and install the application with its
development tools:

```bash
uv sync --extra dev
```

Create your local configuration file:

```bash
cp .env.example .env
```

The `.env`, `credentials/`, and `data/` paths are ignored by Git. Never commit their
contents.

## Configure the layers

Complete each integration guide before starting Whisp:

1. [Configure the Gmail input](inputs/gmail.md)
2. [Configure the OpenRouter processor](processors/openrouter.md)
3. [Configure the Telegram output](outputs/telegram.md)
4. [Personalize your assistant](personalization.md) (optional)

Your `.env` file should then contain values for these required settings:

```env
WHISP_OPENROUTER_API_KEY=sk-or-v1-...
WHISP_TELEGRAM_BOT_TOKEN=...
WHISP_TELEGRAM_CHAT_ID=...
```

The Gmail authorization command stores its token separately in
`credentials/google_token.json`.

## Verify the complete workflow

On the first run, use backfill to summarize recent inbox messages immediately:

```bash
uv run whisp poll --backfill
```

Whisp checks the Telegram bot, reads up to 25 recent inbox messages, sends their content
to the configured OpenRouter model, and delivers each personalized briefing to Telegram.
It prints a result similar to:

```json
{
  "discovered": 3,
  "notified": 3,
  "skipped": 0,
  "failed": 0,
  "initialized": true
}
```

If `failed` is greater than zero, check the terminal log and the troubleshooting section
of the relevant provider guide.

After the first run, a normal poll processes only newly received messages:

```bash
uv run whisp poll
```

## Run continuously

Start the API and background poller locally:

```bash
uv run whisp serve
```

Marketing email (Gmail's Promotions category, or mail the assistant judges to be
marketing) is not notified immediately. It is held and sent as one digest at 23:00
Vietnam time. These optional settings control the digest:

```env
WHISP_DIGEST_ENABLED=true
WHISP_DIGEST_TIME=23:00
WHISP_TIMEZONE=Asia/Ho_Chi_Minh
```

Run `uv run whisp digest` to send the pending digest immediately.

Whisp checks Gmail every 60 seconds by default. The local operational endpoints are:

- `GET http://localhost:8080/healthz`
- `GET http://localhost:8080/readyz`
- `GET http://localhost:8080/status`

`/healthz` only confirms that the process is running. `/readyz` returns a cached readiness
snapshot for SQLite, Gmail, and Telegram, while `/status` includes the latest poll and
sanitized failure details. These endpoints do not make provider requests themselves.

You can inspect the same local state from the terminal:

```bash
uv run whisp status
```

## Run with Docker

Complete Gmail authorization locally before starting the container. Docker mounts the
`credentials/` directory read-only and keeps mutable SQLite state under `data/`.

```bash
docker compose up --build -d
```

Follow the service log with:

```bash
docker compose logs -f whisp
```

## First-run behavior

A normal first run records the current Gmail position and waits for new messages. It does
not summarize existing mail. This prevents an unexpected burst of API usage and Telegram
notifications.

Use `uv run whisp poll --backfill` when you intentionally want to process recent inbox
messages. A message is recorded as processed only after Telegram accepts its notification.
This favors delivery over silence, so a process crash at the exact delivery boundary may
produce one duplicate notification.

## Development checks

Install the development dependencies and run the project checks with:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
```
