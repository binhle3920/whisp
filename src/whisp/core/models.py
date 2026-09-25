from dataclasses import dataclass
from enum import StrEnum


class EmailCategory(StrEnum):
    """Provider-neutral categories an input can assign from its own classification."""

    PROMOTIONAL = "promotional"


@dataclass(frozen=True)
class EmailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    internal_date: str | None = NotImplemented
    category: EmailCategory | None = None


@dataclass(frozen=True)
class ProcessedEmail:
    text: str
    marketing: bool = False


@dataclass(frozen=True)
class DigestItem:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    summary: str | None = None


@dataclass(frozen=True)
class PollResult:
    discovered: int = 0
    notified: int = 0
    skipped: int = 0
    failed: int = 0
    initialized: bool = False
    # Messages discovered but deferred to a later run because this run hit
    # max_messages. The cursor is held back so they are rediscovered.
    pending: int = 0
    # Marketing messages held for the daily digest instead of notified immediately.
    queued: int = 0
