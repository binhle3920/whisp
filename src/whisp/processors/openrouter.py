import asyncio
import json
from typing import Any

import httpx

from whisp.core.errors import ProviderError
from whisp.core.models import EmailMessage, ProcessedEmail
from whisp.processors.base import BaseEmailProcessor
from whisp.processors.profile import AssistantProfile


class OpenRouterProcessor(BaseEmailProcessor):
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        site_url: str | None = None,
        app_title: str = "Whisp",
        profile: AssistantProfile | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client
        self.site_url = site_url
        self.app_title = app_title
        self.profile = profile or AssistantProfile()

    async def process(self, message: EmailMessage) -> ProcessedEmail:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-OpenRouter-Title": self.app_title,
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url

        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = await self.client.post(
                    self.endpoint,
                    headers=headers,
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": self.profile.system_prompt(),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"From: {message.sender}\n"
                                    f"Subject: {message.subject}\n\n{message.body}"
                                ),
                            },
                        ],
                        "max_tokens": 400,
                        "response_format": {"type": "json_object"},
                    },
                )
            except httpx.HTTPError:
                raise ProviderError("OpenRouter", "request") from None
            if response.status_code != 429 and response.status_code < 500:
                break
            if attempt < 2:
                await asyncio.sleep(2**attempt)

        assert response is not None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise ProviderError("OpenRouter", "request", status_code=response.status_code) from None
        try:
            data: dict[str, Any] = response.json()
        except ValueError:
            raise ProviderError("OpenRouter", "response decoding") from None
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenRouter", "response validation") from None
        if not isinstance(content, str):
            raise ProviderError("OpenRouter", "response validation")
        result = _parse_result(content.strip())
        if not result.text:
            raise ProviderError("OpenRouter", "response validation")
        return result


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
