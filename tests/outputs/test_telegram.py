import json

import httpx
import respx

from whisp.core.models import EmailMessage
from whisp.outputs.telegram import TelegramOutput


@respx.mock
async def test_telegram_sends_conversational_plain_text_with_gmail_link() -> None:
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    message = EmailMessage(
        id="message-1",
        thread_id="thread-1",
        sender="Techcombank <offers@techcombank.com>",
        subject="Trả góp 0%",
        body="Offer details",
    )

    async with httpx.AsyncClient() as client:
        output = TelegramOutput("test-token", "123", client)
        await output.send(
            message,
            "**Bạn có ưu đãi trả góp 0%.** [Xem ưu đãi](https://example.com/deal)",
        )

    payload = json.loads(route.calls.last.request.content)
    assert payload == {
        "chat_id": "123",
        "text": (
            "Bạn có ưu đãi trả góp 0%. Xem ưu đãi (https://example.com/deal)\n\n"
            "----\n\n"
            "Từ: Techcombank\n"
            "Mở email: https://mail.google.com/mail/u/0/#inbox/thread-1"
        ),
    }
    assert "subject" not in payload["text"].lower()
    assert "**" not in payload["text"]


@respx.mock
async def test_telegram_keeps_footer_when_truncating_long_content() -> None:
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    message = EmailMessage("message-1", "", "alice@example.com", "Hello", "Body")

    async with httpx.AsyncClient() as client:
        output = TelegramOutput("test-token", "123", client)
        await output.send(message, "x" * 5000)

    text = json.loads(route.calls.last.request.content)["text"]
    assert len(text) == 4096
    assert text.endswith(
        "Từ: alice@example.com\nMở email: https://mail.google.com/mail/u/0/#inbox/message-1"
    )
