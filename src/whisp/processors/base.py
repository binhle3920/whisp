from abc import ABC, abstractmethod
from typing import Any

from whisp.chat.models import ChatCompletion
from whisp.core.models import EmailMessage, ProcessedEmail


class BaseEmailProcessor(ABC):
    @abstractmethod
    async def process(self, message: EmailMessage) -> ProcessedEmail:
        """Transform an email into text for an output provider and classify it."""


class BaseChatModel(ABC):
    @abstractmethod
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        """Run one model turn over OpenAI-style messages and function tools."""
