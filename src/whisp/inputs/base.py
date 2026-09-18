from abc import ABC, abstractmethod

from whisp.core.models import EmailMessage


class InputCursorExpired(Exception):
    """The input provider can no longer continue from the stored cursor."""


class BaseEmailInput(ABC):
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
