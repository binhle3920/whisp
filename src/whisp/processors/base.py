from abc import ABC, abstractmethod

from whisp.core.models import EmailMessage


class BaseEmailProcessor(ABC):
    @abstractmethod
    async def process(self, message: EmailMessage) -> str:
        """Transform an email into text for an output provider."""
