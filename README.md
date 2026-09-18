# Whisp

> An AI layer between your inbox and you.

Whisp is an open-source, self-hosted service that turns incoming email into concise,
useful notifications. It watches your inbox, extracts the readable content, summarizes
the message with an AI model, and delivers the result to the channel where you want to
see it.

The first release is deliberately small and personal:

- Gmail is the inbox provider.
- OpenRouter provides the summarization model.
- Telegram delivers notifications.
- SQLite keeps the Gmail cursor and prevents duplicate notifications.

```text
Input          Processor             Output
Gmail    →     OpenRouter summary    →    Telegram
```

Whisp requests read-only access to Gmail and never modifies your messages. It stores
its operational state locally, making it suitable for running on your laptop, home
server, or private host.

## Documentation

- [Getting started](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Gmail input](docs/inputs/gmail.md)
- [OpenRouter processor](docs/processors/openrouter.md)
- [Telegram output](docs/outputs/telegram.md)
- [Documentation index](docs/README.md)

## Project status

Whisp is an early working release focused on proving the complete email-to-summary
workflow. Future versions can add inbox providers, notification channels, filtering,
priority decisions, and richer self-hosting controls.

## License

AGPL-3.0-or-later.
