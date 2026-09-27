import asyncio
import base64
import re
from typing import Any

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import EmailMessage, EmailSummary
from whisp.http import request_json
from whisp.inputs.base import BaseEmailInput, BaseMailbox, InputCursorExpired
from whisp.inputs.gmail.auth import GmailAuth
from whisp.inputs.gmail.parser import parse_message, parse_summary

MAX_SEARCH_RESULTS = 10
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
# Messages carrying any of these labels are never notified, even when also in the inbox.
EXCLUDED_LABELS = frozenset({"SPAM", "TRASH", "SENT", "DRAFT"})
# Gmail message and attachment ids are URL-safe tokens. The chat assistant passes ids
# chosen by a model, so reject anything that could alter the request path.
_ID = re.compile(r"[A-Za-z0-9_-]{1,1024}")


def _checked_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ProviderError("Gmail", "request (invalid id)")
    return value


class GmailInput(BaseEmailInput, BaseMailbox):
    base_url = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, *, auth: GmailAuth, client: httpx.AsyncClient) -> None:
        self.auth = auth
        self.client = client

    async def _get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        try:
            token = await self.auth.access_token()
        except Exception:
            raise ProviderError("Gmail", "authentication") from None
        try:
            return await request_json(
                self.client,
                "GET",
                f"{self.base_url}/{path}",
                provider="Gmail",
                operation="request",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except ProviderError as error:
            if error.status_code == 404 and path == "history":
                raise InputCursorExpired from None
            raise

    async def current_cursor(self) -> str:
        profile = await self._get("profile")
        return str(profile["historyId"])

    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        payload = await self._get(f"messages/{_checked_id(message_id)}", [("format", "full")])
        return parse_message(payload, max_chars=max_chars)

    async def search(self, query: str, *, limit: int) -> list[EmailSummary]:
        limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        data = await self._get("messages", [("q", query), ("maxResults", str(limit))])
        ids = [item["id"] for item in data.get("messages", [])]
        headers = [("format", "metadata")] + [
            ("metadataHeaders", name) for name in ("From", "Subject", "Date")
        ]
        payloads = await asyncio.gather(
            *(self._get(f"messages/{message_id}", headers) for message_id in ids)
        )
        return [parse_summary(payload) for payload in payloads]

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        data = await self._get(
            f"messages/{_checked_id(message_id)}/attachments/{_checked_id(attachment_id)}"
        )
        if int(data.get("size", 0)) > MAX_ATTACHMENT_BYTES:
            raise ProviderError("Gmail", "attachment download (file too large)")
        encoded = data.get("data")
        if not isinstance(encoded, str):
            raise ProviderError("Gmail", "attachment decoding")
        try:
            return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except ValueError:
            raise ProviderError("Gmail", "attachment decoding") from None

    async def recent_message_ids(self, limit: int) -> list[str]:
        data = await self._get(
            "messages", [("q", "in:inbox -in:spam -in:trash"), ("maxResults", str(limit))]
        )
        return [item["id"] for item in data.get("messages", [])]

    async def changes(self, cursor: str) -> tuple[list[str], str]:
        ids: list[str] = []
        page_token: str | None = None
        latest_cursor = cursor
        while True:
            params = [
                ("startHistoryId", cursor),
                ("historyTypes", "messageAdded"),
                ("maxResults", "500"),
            ]
            if page_token:
                params.append(("pageToken", page_token))
            data = await self._get("history", params)
            latest_cursor = data.get("historyId", latest_cursor)
            for event in data.get("history", []):
                for added in event.get("messagesAdded", []):
                    message = added.get("message", {})
                    labels = set(message.get("labelIds", []))
                    if "INBOX" in labels and not labels & EXCLUDED_LABELS:
                        ids.append(message["id"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return list(dict.fromkeys(ids)), latest_cursor
