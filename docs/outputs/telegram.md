# Telegram output

The Telegram output formats the processed email and delivers it through a bot. It only
sends messages; it does not run commands or read Telegram conversations.

## What you need

- A Telegram account
- A bot token from [@BotFather](https://t.me/BotFather)
- The numeric ID of the destination chat

Telegram documents bot creation in its
[BotFather guide](https://core.telegram.org/bots/features#botfather).

## Create the bot

1. Open a chat with [@BotFather](https://t.me/BotFather).
2. Send `/newbot`.
3. Choose a display name, such as `Whisp`.
4. Choose a unique username ending in `bot`, such as `my_whisp_bot`.
5. Copy the bot token returned by BotFather.
6. Add it to `.env`:

```env
WHISP_TELEGRAM_BOT_TOKEN=123456789:replace-with-your-token
```

Treat the bot token as a password. Anyone with it can control the bot.

## Find your chat ID

1. Open your new bot in Telegram.
2. Select **Start** or send `/start`.
3. Open this URL after replacing `<TOKEN>`:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

4. Find `message.chat.id` in the JSON response.
5. Add the numeric value to `.env`:

```env
WHISP_TELEGRAM_CHAT_ID=123456789
```

A direct-message chat ID is normally positive. Group and channel IDs may be negative and
often begin with `-100`. Keep the leading minus sign.

## Use a group instead of a direct message

1. Add the bot to the Telegram group.
2. Send a message in the group that the bot can receive.
3. Call `getUpdates` again.
4. Copy that event's `message.chat.id` into `WHISP_TELEGRAM_CHAT_ID`.

A direct chat is the simplest setup for a personal Whisp installation.

## Verify the output

The manual poll command checks the bot token before processing email:

```bash
uv run whisp poll --backfill
```

If configuration is valid and a recent email is processed, the bot sends a short,
conversational plain-text notification. The AI-written message comes first; a compact
sender section and a direct Gmail link appear below a plain-text divider at the bottom.
When available, the sender's display name and actual email address are shown separately
so misleading display names are easier to spot. The subject is not repeated.

Whisp sends plain text without Telegram parse mode. This prevents email or model-generated
punctuation from breaking Markdown or HTML formatting. It also removes common Markdown
markers if a model returns them despite the prompt.

## Troubleshooting

### `getUpdates` returns an empty result

Open the bot chat and send `/start`, then reload the URL.

### 401 Unauthorized

The bot token is invalid or revoked. Obtain a valid token from BotFather and update
`WHISP_TELEGRAM_BOT_TOKEN`.

### 400 chat not found

Confirm that you sent a message to the bot before copying the chat ID. Preserve a leading
minus sign for groups or channels.

### Bot was blocked by the user

Open the bot chat, unblock it, and select **Start** before polling again.

### Notification is too long

Telegram limits a message to 4,096 characters. Whisp truncates oversized notification
text before sending it.
