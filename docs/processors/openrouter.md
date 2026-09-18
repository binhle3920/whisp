# OpenRouter processor

The OpenRouter processor turns an email into a personalized inbox briefing. Whisp sends
the extracted email text and your assistant profile to OpenRouter, then uses the returned
text as the processor result.

## What you need

- An [OpenRouter](https://openrouter.ai/) account
- An API key
- Enough account credit for the selected model

See the official [OpenRouter quickstart](https://openrouter.ai/docs/quickstart) for API
account details.

## Create an API key

1. Sign in to OpenRouter.
2. Open [API Keys](https://openrouter.ai/settings/keys).
3. Create a key for Whisp.
4. Store the key in `.env`:

```env
WHISP_OPENROUTER_API_KEY=sk-or-v1-...
```

Do not put the key in `.env.example`, source code, screenshots, issues, or Git commits.

## Choose a model

Whisp defaults to a small, inexpensive model suitable for short summaries:

```env
WHISP_OPENROUTER_MODEL=openai/gpt-5.4-nano
```

You can replace this with any compatible text model slug from the
[OpenRouter model catalog](https://openrouter.ai/models). Changing the model does not
require a code change.

Model availability, pricing, and exact slugs can change. Copy the slug from the model's
OpenRouter page and check its current price before processing a large inbox.

## Optional application attribution

These OpenRouter analytics settings are optional:

```env
WHISP_OPENROUTER_SITE_URL=https://your-project.example
WHISP_OPENROUTER_APP_TITLE=Whisp
```

Whisp sends these values as `HTTP-Referer` and `X-OpenRouter-Title`. Leave the site URL
empty for a private local installation.

## Verify the processor

After configuring the input and output, run:

```bash
uv run whisp poll --backfill
```

A successful request produces a Telegram message containing a personalized briefing.
You can also inspect usage and cost from your OpenRouter activity page.

To control the assistant's personality, language, priorities, and knowledge about you,
follow the [personalization guide](../personalization.md).

## Data handling

For each processed message, Whisp sends these fields through OpenRouter:

- Sender
- Subject
- Extracted plain-text message body, truncated to the configured maximum length

Attachments are not uploaded. Review the privacy and data-retention policies of
OpenRouter and the selected model provider before using Whisp with sensitive email.

## Troubleshooting

### 401 Unauthorized

Check that `WHISP_OPENROUTER_API_KEY` contains the complete key and has no surrounding
quotes or spaces. Replace the key if it was revoked.

### 402 or insufficient credits

Add credit to the OpenRouter account or select a model available under your limits.

### 404 model not found

Confirm the exact provider/model slug in `WHISP_OPENROUTER_MODEL`.

### 429 rate limited

Whisp retries rate limits and temporary server errors up to three times. If the batch
still fails, wait before polling again or choose a provider with available capacity.

### Empty or poor responses

Review your assistant profile and try another model slug. Whisp asks for a concise,
actionable briefing containing the reason the email matters, the next action, deadlines,
and important numbers.
