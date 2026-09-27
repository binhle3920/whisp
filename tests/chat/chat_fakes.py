from typing import Any

from whisp.chat.models import ChatCompletion, ToolResult
from whisp.chat.web import WebFetcher
from whisp.core.models import Attachment, EmailMessage, EmailSummary
from whisp.inputs.base import BaseMailbox
from whisp.processors.base import BaseChatModel


class FakeMailbox(BaseMailbox):
    def __init__(self, messages: dict[str, EmailMessage] | None = None) -> None:
        self.messages = messages or {}
        self.files: dict[str, bytes] = {}
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int) -> list[EmailSummary]:
        self.queries.append(query)
        return [
            EmailSummary(m.id, m.sender, m.subject, "Fri, 25 Sep 2026", m.body[:40])
            for m in self.messages.values()
        ][:limit]

    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        return self.messages[message_id]

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return self.files[attachment_id]


class FakeFetcher(WebFetcher):
    def __init__(self) -> None:
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> ToolResult:
        self.fetched.append(url)
        return ToolResult(text=f"Page at {url}")


class ScriptedModel(BaseChatModel):
    """Returns queued completions and records what the agent sent each turn."""

    def __init__(self, *completions: ChatCompletion) -> None:
        self.completions = list(completions)
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        self.calls.append(([dict(m) for m in messages], tools))
        return self.completions.pop(0)


def invoice_email() -> EmailMessage:
    return EmailMessage(
        id="m1",
        thread_id="t1",
        sender="Billing <billing@acme.com>",
        subject="Invoice September",
        body="Your invoice is attached. Pay at https://acme.com/pay?id=42 before Friday.",
        internal_date="1790000000000",
        attachments=(Attachment("att-1", "invoice.csv", "text/csv", 20),),
    )
