import asyncio
from typing import Any

import httpx

from whisp.core.models import EmailMessage
from whisp.processors.base import BaseEmailProcessor


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
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client
        self.site_url = site_url
        self.app_title = app_title

    async def process(self, message: EmailMessage) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-OpenRouter-Title": self.app_title,
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url

        response: httpx.Response | None = None
        for attempt in range(3):
            response = await self.client.post(
                self.endpoint,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Summarize this email for its recipient. Use the email's "
                                "language. Write 2-4 concise sentences. State the main point, "
                                "required action, and any deadline or important number. Do not "
                                "invent facts. Output only the summary."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"From: {message.sender}\n"
                                f"Subject: {message.subject}\n\n{message.body}"
                            ),
                        },
                    ],
                    "max_tokens": 300,
                },
            )
            if response.status_code != 429 and response.status_code < 500:
                break
            if attempt < 2:
                await asyncio.sleep(2**attempt)

        assert response is not None
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenRouter returned an unexpected response") from exc
        if not isinstance(content, str):
            raise RuntimeError("OpenRouter returned non-text content")
        summary = content.strip()
        if not summary:
            raise RuntimeError("OpenRouter returned an empty summary")
        return summary
