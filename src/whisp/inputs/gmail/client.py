from typing import Any

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import EmailMessage
from whisp.inputs.base import BaseEmailInput, InputCursorExpired
from whisp.inputs.gmail.auth import GmailAuth
from whisp.inputs.gmail.parser import parse_message


class GmailInput(BaseEmailInput):
    base_url = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, auth: GmailAuth, client: httpx.AsyncClient) -> None:
        self.auth = auth
        self.client = client

    async def _get(self, path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        try:
            token = await self.auth.access_token()
        except Exception:
            raise ProviderError("Gmail", "authentication") from None
        try:
            response = await self.client.get(
                f"{self.base_url}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            raise ProviderError("Gmail", "request") from None
        if response.status_code == 404 and path == "history":
            raise InputCursorExpired
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise ProviderError("Gmail", "request", status_code=response.status_code) from None
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("Gmail", "response decoding") from None
        if not isinstance(data, dict):
            raise ProviderError("Gmail", "response decoding")
        return data

    async def current_cursor(self) -> str:
        profile = await self._get("profile")
        return str(profile["historyId"])

    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        payload = await self._get(f"messages/{message_id}", [("format", "full")])
        return parse_message(payload, max_chars=max_chars)

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
                    blocked = {"SPAM", "TRASH", "SENT", "DRAFT"}
                    if "INBOX" in labels and not labels.intersection(blocked):
                        ids.append(message["id"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return list(dict.fromkeys(ids)), latest_cursor
