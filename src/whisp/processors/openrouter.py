import asyncio
import json
from typing import Any

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import ChatCompletion, EmailMessage, ProcessedEmail, ToolCall
from whisp.http import request_json
from whisp.processors.base import BaseChatModel, BaseEmailProcessor
from whisp.processors.profile import AssistantProfile

ATTEMPTS = 3


def _retryable(error: ProviderError) -> bool:
    return error.status_code is not None and (error.status_code == 429 or error.status_code >= 500)


class _OpenRouterClient:
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        site_url: str | None = None,
        app_title: str = "Whisp",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client
        self.site_url = site_url
        self.app_title = app_title

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST one completion request with retries; return the first choice's message."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-OpenRouter-Title": self.app_title,
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url

        for attempt in range(ATTEMPTS):
            try:
                data = await request_json(
                    self.client,
                    "POST",
                    self.endpoint,
                    provider="OpenRouter",
                    operation="request",
                    headers=headers,
                    json={"model": self.model, **payload},
                )
                break
            except ProviderError as error:
                if not _retryable(error) or attempt == ATTEMPTS - 1:
                    raise
                await asyncio.sleep(2**attempt)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenRouter", "response validation") from None
        if not isinstance(message, dict):
            raise ProviderError("OpenRouter", "response validation")
        return message


class OpenRouterProcessor(_OpenRouterClient, BaseEmailProcessor):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        profile: AssistantProfile,
        site_url: str | None = None,
        app_title: str = "Whisp",
    ) -> None:
        super().__init__(
            api_key=api_key, model=model, client=client, site_url=site_url, app_title=app_title
        )
        self.profile = profile

    async def process(self, message: EmailMessage) -> ProcessedEmail:
        reply = await self._post(
            {
                "messages": [
                    {"role": "system", "content": self.profile.system_prompt()},
                    {
                        "role": "user",
                        "content": (
                            f"From: {message.sender}\nSubject: {message.subject}\n\n{message.body}"
                        ),
                    },
                ],
                "max_tokens": 400,
                "response_format": {"type": "json_object"},
            }
        )
        content = reply.get("content")
        if not isinstance(content, str):
            raise ProviderError("OpenRouter", "response validation")
        result = _parse_result(content.strip())
        if not result.text:
            raise ProviderError("OpenRouter", "response validation")
        return result


class OpenRouterChatModel(_OpenRouterClient, BaseChatModel):
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ChatCompletion:
        payload: dict[str, Any] = {"messages": messages, "max_tokens": 1200}
        if tools:
            payload["tools"] = tools
        reply = await self._post(payload)
        calls = []
        for call in reply.get("tool_calls") or []:
            try:
                function = call["function"]
                calls.append(
                    ToolCall(
                        id=str(call["id"]),
                        name=str(function["name"]),
                        arguments=str(function.get("arguments") or "{}"),
                    )
                )
            except (KeyError, TypeError):
                raise ProviderError("OpenRouter", "response validation") from None
        content = reply.get("content")
        text = content.strip() if isinstance(content, str) and content.strip() else None
        if text is None and not calls:
            raise ProviderError("OpenRouter", "response validation")
        return ChatCompletion(text=text, tool_calls=tuple(calls))


def _parse_result(content: str) -> ProcessedEmail:
    # Fail open: if the model ignores the JSON contract, deliver its text immediately
    # rather than holding it for the digest. A formatting slip must never delay real mail.
    try:
        data = json.loads(content)
    except ValueError:
        return ProcessedEmail(text=content)
    if not isinstance(data, dict):
        return ProcessedEmail(text=content)
    notification = data.get("notification")
    if not isinstance(notification, str):
        return ProcessedEmail(text=content)
    return ProcessedEmail(text=notification.strip(), marketing=data.get("marketing") is True)
