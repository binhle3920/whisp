import re
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import DigestItem, EmailMessage
from whisp.http import request_json
from whisp.outputs.base import BaseNotificationOutput

MESSAGE_LIMIT = 4096
SUBJECT_LIMIT = 200


class TelegramOutput(BaseNotificationOutput):
    def __init__(self, *, token: str, chat_id: str, client: httpx.AsyncClient) -> None:
        self.api = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.client = client

    async def check(self) -> None:
        await self._request("check", "GET", "getMe")

    async def send(self, message: EmailMessage, processed_text: str) -> str | None:
        sender_name, sender_address = parseaddr(message.sender)
        sender_name = _one_line(sender_name, 120)
        sender_address = _one_line(sender_address, 254)
        if sender_name and sender_address:
            sender_details = f"Từ: {sender_name}\nEmail: {sender_address}"
        else:
            sender_details = f"Từ: {sender_address or _one_line(message.sender, 254)}"
        gmail_id = quote(message.thread_id or message.id, safe="")
        gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{gmail_id}"

        content = _plain_text(processed_text)
        divider = "----"
        content_limit = MESSAGE_LIMIT - len(sender_details) - len(divider) - 4
        if len(content) > content_limit:
            content = content[: content_limit - 3].rstrip() + "..."
        text = f"{content}\n\n{divider}\n\n{sender_details}"
        data = await self._request(
            "send",
            "POST",
            "sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "reply_markup": {"inline_keyboard": [[{"text": "Mở email", "url": gmail_url}]]},
            },
        )
        return _message_id(data)

    async def send_text(self, chat_id: str, text: str, *, reply_to: str | None = None) -> None:
        """Send a chat reply, split across messages when it exceeds Telegram's limit."""
        for index, chunk in enumerate(_split(_plain_text(text) or "…")):
            payload: dict[str, object] = {"chat_id": chat_id, "text": chunk}
            if index == 0 and reply_to:
                payload["reply_parameters"] = {
                    "message_id": int(reply_to),
                    "allow_sending_without_reply": True,
                }
            await self._request("reply", "POST", "sendMessage", json=payload)

    async def send_typing(self, chat_id: str) -> None:
        await self._request(
            "typing", "POST", "sendChatAction", json={"chat_id": chat_id, "action": "typing"}
        )

    async def set_webhook(self, url: str, secret: str) -> None:
        await self._request(
            "webhook registration",
            "POST",
            "setWebhook",
            json={"url": url, "secret_token": secret, "allowed_updates": ["message"]},
        )

    async def send_digest(self, items: list[DigestItem]) -> None:
        header = f"📬 Email quảng cáo hôm nay ({len(items)})"
        entries = [_digest_entry(index, item) for index, item in enumerate(items, start=1)]
        for text in _chunk([header, *entries]):
            await self._request(
                "digest", "POST", "sendMessage", json={"chat_id": self.chat_id, "text": text}
            )

    async def _request(
        self, operation: str, method: str, api_method: str, **kwargs: Any
    ) -> dict[str, Any]:
        data = await request_json(
            self.client,
            method,
            f"{self.api}/{api_method}",
            provider="Telegram",
            operation=operation,
            **kwargs,
        )
        if not data.get("ok"):
            raise ProviderError("Telegram", operation)
        return data


def _one_line(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _digest_entry(index: int, item: DigestItem) -> str:
    sender_name, sender_address = parseaddr(item.sender)
    sender = _one_line(sender_name or sender_address or item.sender, 120)
    subject = _one_line(item.subject, SUBJECT_LIMIT)
    entry = f"{index}. {sender} — {subject}"
    if item.summary:
        entry += f"\n   {_plain_text(item.summary)}"
    return entry[:MESSAGE_LIMIT]


def _message_id(data: dict[str, Any]) -> str | None:
    result = data.get("result")
    if isinstance(result, dict) and "message_id" in result:
        return str(result["message_id"])
    return None


def _split(text: str) -> list[str]:
    """Split long text between paragraphs, hard-cutting only a paragraph that is too long."""
    blocks: list[str] = []
    for paragraph in text.split("\n\n"):
        while len(paragraph) > MESSAGE_LIMIT:
            blocks.append(paragraph[:MESSAGE_LIMIT])
            paragraph = paragraph[MESSAGE_LIMIT:]
        blocks.append(paragraph)
    return _chunk(blocks)


def _chunk(blocks: list[str]) -> list[str]:
    """Pack blocks into as few messages as fit Telegram's limit, splitting only between blocks."""
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > MESSAGE_LIMIT and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


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
