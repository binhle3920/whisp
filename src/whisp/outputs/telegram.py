import re
from email.utils import parseaddr
from urllib.parse import quote

import httpx

from whisp.core.models import EmailMessage
from whisp.outputs.base import BaseNotificationOutput


class TelegramOutput(BaseNotificationOutput):
    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = client

    async def check(self) -> None:
        response = await self.client.get(self.url.replace("sendMessage", "getMe"))
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram rejected the bot token")

    async def send(self, message: EmailMessage, processed_text: str) -> None:
        sender_name, sender_address = parseaddr(message.sender)
        sender = sender_name or sender_address or message.sender
        sender = re.sub(r"\s+", " ", sender).strip()[:120]
        gmail_id = quote(message.thread_id or message.id, safe="")
        footer = f"Từ: {sender}\nMở email: https://mail.google.com/mail/u/0/#inbox/{gmail_id}"

        content = _plain_text(processed_text)
        divider = "----"
        content_limit = 4096 - len(footer) - len(divider) - 4
        if len(content) > content_limit:
            content = content[: content_limit - 3].rstrip() + "..."
        text = f"{content}\n\n{divider}\n\n{footer}"
        response = await self.client.post(self.url, json={"chat_id": self.chat_id, "text": text})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram send failed: {data.get('description', 'unknown error')}")


def _plain_text(value: str) -> str:
    """Remove common model-generated Markdown while preserving readable text and links."""
    text = value.strip()
    text = re.sub(r"```(?:\w+)?\n?|```", "", text)
    text = re.sub(r"\[([^\]]+)]\((https?://[^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "• ", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)([*_])([^\n]+?)\1(?!\w)", r"\2", text)
    text = text.replace("`", "")
    return text.strip()
