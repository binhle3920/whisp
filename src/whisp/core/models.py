from dataclasses import dataclass


@dataclass(frozen=True)
class EmailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    internal_date: str | None = None


@dataclass(frozen=True)
class PollResult:
    discovered: int = 0
    notified: int = 0
    skipped: int = 0
    failed: int = 0
    initialized: bool = False

