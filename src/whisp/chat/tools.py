import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from whisp.chat.documents import UnsupportedDocument, extract
from whisp.chat.models import ToolResult
from whisp.chat.web import WebFetcher, normalize_url
from whisp.core.errors import safe_error_message
from whisp.core.models import EmailMessage
from whisp.inputs.base import BaseMailbox
from whisp.text import find_urls

logger = logging.getLogger(__name__)

DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_emails",
            "description": (
                "Search the user's mailbox with Gmail search syntax, e.g. "
                "'from:alice subject:contract after:2026/09/01 has:attachment'. "
                "Returns id, sender, subject, date and a snippet for each match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_email",
            "description": "Read one email's full text and list its attachments.",
            "parameters": {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_attachment",
            "description": (
                "Read an attachment of an email (PDF, Word, Excel, CSV, text, HTML or "
                "image). Use the exact filename listed by read_email."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["message_id", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": (
                "Open a web page and return its text. Only links that appear in an email "
                "you have read or in the user's own message can be opened."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


def untrusted(source: str, content: str) -> str:
    # The closing tag is neutralized so content cannot end the block early and smuggle
    # text that the model would read as outside the untrusted region.
    safe = content.replace("</untrusted>", "</untrusted_>")
    return f'<untrusted source="{source}">\n{safe}\n</untrusted>'


class MailTools:
    """The assistant's tools for one request. Holds which URLs it may fetch."""

    def __init__(
        self,
        *,
        mailbox: BaseMailbox,
        fetcher: WebFetcher,
        email_max_chars: int,
        allowed_urls: set[str] | None = None,
    ) -> None:
        self.mailbox = mailbox
        self.fetcher = fetcher
        self.email_max_chars = email_max_chars
        self.allowed_urls = set(allowed_urls or ())

    def allow_urls_in(self, text: str) -> None:
        for url in find_urls(text):
            try:
                self.allowed_urls.add(normalize_url(url))
            except Exception:
                continue

    async def call(self, name: str, arguments: str) -> ToolResult:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return ToolResult(text="Error: tool arguments must be a JSON object.")
        handler = {
            "search_emails": self._search,
            "read_email": self._read_email,
            "read_attachment": self._read_attachment,
            "fetch_webpage": self._fetch_webpage,
        }.get(name)
        if handler is None:
            return ToolResult(text=f"Error: unknown tool {name}.")
        try:
            return await handler(args)
        except (KeyError, TypeError, ValueError):
            return ToolResult(text=f"Error: invalid arguments for {name}.")
        except Exception as exc:
            # The model gets a sanitized reason so it can tell the user or try another
            # approach; raw provider errors never reach the model or the logs.
            message = safe_error_message(exc)
            logger.warning("Chat tool %s failed: %s", name, message)
            return ToolResult(text=f"Error: {message}.")

    async def _search(self, args: dict[str, Any]) -> ToolResult:
        query = str(args["query"])
        limit = int(args.get("max_results", 5))
        results = await self.mailbox.search(query, limit=limit)
        if not results:
            return ToolResult(text="No emails matched.")
        lines = [
            f"- id={item.id} | {item.date} | From: {item.sender} | Subject: {item.subject}\n"
            f"  {item.snippet}"
            for item in results
        ]
        return ToolResult(text=untrusted("search results", "\n".join(lines)))

    async def _read_email(self, args: dict[str, Any]) -> ToolResult:
        message = await self.mailbox.fetch(str(args["message_id"]), max_chars=self.email_max_chars)
        self.allow_urls_in(message.body)
        attachments = (
            "\n".join(
                f"- {item.filename} ({item.mime_type}, {item.size} bytes)"
                for item in message.attachments
            )
            or "none"
        )
        text = (
            f"From: {message.sender}\nSubject: {message.subject}\nDate: {_date(message)}\n"
            f"Attachments:\n{attachments}\n\n{message.body}"
        )
        return ToolResult(text=untrusted("email", text))

    async def _read_attachment(self, args: dict[str, Any]) -> ToolResult:
        message_id = str(args["message_id"])
        filename = str(args["filename"])
        # Attachment ids are not stable between fetches, so look the file up by name on a
        # fresh copy of the message instead of trusting an id the model remembered.
        message = await self.mailbox.fetch(message_id, max_chars=self.email_max_chars)
        attachment = next((item for item in message.attachments if item.filename == filename), None)
        if attachment is None:
            names = ", ".join(item.filename for item in message.attachments) or "none"
            return ToolResult(text=f"Error: no attachment named {filename}. Available: {names}.")
        data = await self.mailbox.download_attachment(message_id, attachment.id)
        try:
            # Parsing is CPU-bound; keep it off the event loop that serves webhooks.
            result = await asyncio.to_thread(
                extract, attachment.filename, attachment.mime_type, data
            )
        except UnsupportedDocument as exc:
            return ToolResult(text=f"Error: {exc}.")
        self.allow_urls_in(result.text)
        return ToolResult(
            text=untrusted(f"attachment {attachment.filename}", result.text), images=result.images
        )

    async def _fetch_webpage(self, args: dict[str, Any]) -> ToolResult:
        url = normalize_url(str(args["url"]))
        if url not in self.allowed_urls:
            # Refusing model-invented URLs stops injected instructions from smuggling
            # mailbox data out in a query string.
            return ToolResult(
                text=(
                    "Error: this link is not allowed. Only links that appear in an email "
                    "you have read, or in the user's message, can be opened."
                )
            )
        result = await self.fetcher.fetch(url)
        return ToolResult(text=untrusted("web page", result.text), images=result.images)


def _date(message: EmailMessage) -> str:
    if not message.internal_date:
        return "unknown"
    try:
        stamp = datetime.fromtimestamp(int(message.internal_date) / 1000, tz=UTC)
    except (ValueError, OverflowError):
        return "unknown"
    return stamp.isoformat(timespec="minutes")
