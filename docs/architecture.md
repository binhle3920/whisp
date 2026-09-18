# Architecture

Whisp separates external providers into three layers around a small, provider-independent
core.

```text
┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Input          │    │ Processor      │    │ Output         │
│                │    │                │    │                │
│ Gmail          │───▶│ OpenRouter     │───▶│ Telegram       │
│                │    │ assistant      │    │ notification   │
└────────────────┘    └────────────────┘    └────────────────┘
         │                     ▲                     ▲
         └─────────────────────┴─────────────────────┘
                         Core pipeline
```

## Layer responsibilities

| Layer | Contract | Responsibility |
|---|---|---|
| Input | `BaseEmailInput` | Detect external messages and convert them into `EmailMessage` values. |
| Processor | `BaseEmailProcessor` | Transform an `EmailMessage` into processed text. |
| Output | `BaseNotificationOutput` | Format and deliver the processed result. |
| Core | `Pipeline` | Coordinate the layers, persistence, retries, cursors, and deduplication. |

The core imports only the three layer contracts. Provider implementations may import core
models, but the core never imports Gmail, OpenRouter, or Telegram.

## Source layout

```text
src/whisp/
├── core/
│   ├── models.py
│   ├── pipeline.py
│   └── store.py
├── inputs/
│   ├── base.py
│   └── gmail/
│       ├── auth.py
│       ├── client.py
│       └── parser.py
├── processors/
│   ├── base.py
│   └── openrouter.py
├── outputs/
│   ├── base.py
│   └── telegram.py
├── app.py
├── cli.py
├── config.py
└── runtime.py
```

`runtime.py` is the composition root. It reads configuration, constructs the selected
provider for each layer, and injects those providers into the pipeline. `app.py` and
`cli.py` expose the same composed workflow through HTTP, a background poller, and commands.

## Processing sequence

1. The input reports message IDs after its stored cursor.
2. The core skips IDs already recorded in SQLite.
3. The input converts each provider payload into a common `EmailMessage`.
4. The processor transforms the message into a personalized briefing.
5. The output formats and delivers the notification.
6. The core records the message as processed and advances the cursor after a successful
   batch.

The delivery record is written after the output accepts the message. This gives Whisp
at-least-once delivery: a crash at the delivery boundary may repeat one notification, but
does not silently lose it.

## Adding a provider

Add a provider inside the layer it implements:

- An inbox or event source inherits `BaseEmailInput` under `inputs/`.
- An assistant, summarizer, or classifier inherits `BaseEmailProcessor` under `processors/`.
- A notification destination inherits `BaseNotificationOutput` under `outputs/`.

Keep provider-specific authentication, payload parsing, retries, and formatting inside
that provider package. Add its configuration and wire it in `runtime.py`; the core
pipeline should not change.
