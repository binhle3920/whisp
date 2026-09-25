from abc import ABC, abstractmethod

from whisp.core.models import EmailMessage, ProcessedEmail


class BaseEmailProcessor(ABC):
    @abstractmethod
    async def process(self, message: EmailMessage) -> ProcessedEmail:
        """Transform an email into text for an output provider and classify it."""
