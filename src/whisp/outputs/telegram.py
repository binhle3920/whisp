import httpx

from whisp.core.models import EmailMessage
from whisp.outputs.base import BaseNotificationOutput


class TelegramOutput(BaseNotificationOutput):
    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = client

    async def check(self) -> None:
        response = await self.client.get(self.url.replace("sendMessage", "getMe"))
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram rejected the bot token")

    async def send(self, message: EmailMessage, processed_text: str) -> None:
        text = (
            f"New email\n\nFrom: {message.sender}\nSubject: {message.subject}"
            f"\n\n{processed_text}"
        )
        if len(text) > 4096:
            text = text[:4093] + "..."
        response = await self.client.post(
            self.url, json={"chat_id": self.chat_id, "text": text}
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram send failed: {data.get('description', 'unknown error')}")
