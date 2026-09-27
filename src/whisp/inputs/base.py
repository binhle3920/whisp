from abc import ABC, abstractmethod

from whisp.core.models import EmailMessage, EmailSummary


class InputCursorExpired(Exception):
    """The input provider can no longer continue from the stored cursor."""


class BaseEmailInput(ABC):
    async def check(self) -> None:
        """Validate that the input provider can be reached."""
        await self.current_cursor()

    @abstractmethod
    async def current_cursor(self) -> str:
        """Return the provider's current position."""

    @abstractmethod
    async def recent_message_ids(self, limit: int) -> list[str]:
        """Return recent message IDs for an intentional backfill."""

    @abstractmethod
    async def changes(self, cursor: str) -> tuple[list[str], str]:
        """Return message IDs after a cursor and the next cursor."""

    @abstractmethod
    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        """Fetch and normalize one provider message."""


class BaseMailbox(ABC):
    """Read-only access to a mailbox for the chat assistant."""

    @abstractmethod
    async def search(self, query: str, *, limit: int) -> list[EmailSummary]:
        """Return messages matching a provider search query, newest first."""

    @abstractmethod
    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        """Fetch and normalize one provider message, including its attachment list."""

    @abstractmethod
    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Return the raw bytes of one attachment."""
