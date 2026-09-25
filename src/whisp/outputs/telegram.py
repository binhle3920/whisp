import re
from email.utils import parseaddr
from urllib.parse import quote

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import DigestItem, EmailMessage
from whisp.outputs.base import BaseNotificationOutput

MESSAGE_LIMIT = 4096
SUBJECT_LIMIT = 200


class TelegramOutput(BaseNotificationOutput):
    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = client

    async def check(self) -> None:
        await self._request("check", self.client.get, self.url.replace("sendMessage", "getMe"))

    async def send(self, message: EmailMessage, processed_text: str) -> None:
        sender_name, sender_address = parseaddr(message.sender)
        sender_name = re.sub(r"\s+", " ", sender_name).strip()[:120]
        sender_address = re.sub(r"\s+", " ", sender_address).strip()[:254]
        if sender_name and sender_address:
            sender_details = f"Từ: {sender_name}\nEmail: {sender_address}"
        else:
            sender = sender_address or re.sub(r"\s+", " ", message.sender).strip()[:254]
            sender_details = f"Từ: {sender}"
        gmail_id = quote(message.thread_id or message.id, safe="")
        gmail_url = f"https://mail.google.com/mail/u/0/#inbox/{gmail_id}"

        content = _plain_text(processed_text)
        divider = "----"
        content_limit = MESSAGE_LIMIT - len(sender_details) - len(divider) - 4
        if len(content) > content_limit:
            content = content[: content_limit - 3].rstrip() + "..."
        text = f"{content}\n\n{divider}\n\n{sender_details}"
        await self._request(
            "send",
            self.client.post,
            self.url,
            json={
                "chat_id": self.chat_id,
                "text": text,
                "reply_markup": {"inline_keyboard": [[{"text": "Mở email", "url": gmail_url}]]},
            },
        )

    async def send_digest(self, items: list[DigestItem]) -> None:
        header = f"📬 Email quảng cáo hôm nay ({len(items)})"
        entries = [_digest_entry(index, item) for index, item in enumerate(items, start=1)]
        for text in _chunk([header, *entries]):
            await self._request(
                "digest",
                self.client.post,
                self.url,
                json={"chat_id": self.chat_id, "text": text},
            )

    async def _request(self, operation: str, request, url: str, **kwargs):
        try:
            response = await request(url, **kwargs)
        except httpx.HTTPError:
            raise ProviderError("Telegram", operation) from None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise ProviderError("Telegram", operation, status_code=response.status_code) from None
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("Telegram", f"{operation} response decoding") from None
        if not isinstance(data, dict) or not data.get("ok"):
            raise ProviderError("Telegram", operation)
        return data


def _digest_entry(index: int, item: DigestItem) -> str:
    sender_name, sender_address = parseaddr(item.sender)
    sender = re.sub(r"\s+", " ", sender_name or sender_address or item.sender).strip()[:120]
    subject = re.sub(r"\s+", " ", item.subject).strip()[:SUBJECT_LIMIT]
    entry = f"{index}. {sender} — {subject}"
    if item.summary:
        entry += f"\n   {_plain_text(item.summary)}"
    return entry[:MESSAGE_LIMIT]


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
