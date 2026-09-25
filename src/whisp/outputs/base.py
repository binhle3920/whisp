from abc import ABC, abstractmethod

from whisp.core.models import DigestItem, EmailMessage


class BaseNotificationOutput(ABC):
    @abstractmethod
    async def check(self) -> None:
        """Validate that the output provider is ready."""

    @abstractmethod
    async def send(self, message: EmailMessage, processed_text: str) -> None:
        """Deliver one processed email."""

    @abstractmethod
    async def send_digest(self, items: list[DigestItem]) -> None:
        """Deliver a batch of held marketing emails as one digest."""
