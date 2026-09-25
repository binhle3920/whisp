import json

import httpx
import pytest
import respx

from whisp.core.errors import ProviderError
from whisp.core.models import DigestItem, EmailMessage
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
            "Email: offers@techcombank.com"
        ),
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "Mở email",
                        "url": "https://mail.google.com/mail/u/0/#inbox/thread-1",
                    }
                ]
            ]
        },
    }
    assert "mail.google.com" not in payload["text"]
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
    assert text.endswith("Từ: alice@example.com")


@respx.mock
async def test_telegram_button_uses_message_id_when_thread_id_is_missing() -> None:
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    message = EmailMessage("message/id", "", "alice@example.com", "Hello", "Body")

    async with httpx.AsyncClient() as client:
        output = TelegramOutput("test-token", "123", client)
        await output.send(message, "Summary")

    payload = json.loads(route.calls.last.request.content)
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button == {
        "text": "Mở email",
        "url": "https://mail.google.com/mail/u/0/#inbox/message%2Fid",
    }


@respx.mock
async def test_telegram_failure_does_not_expose_token_or_request_url() -> None:
    token = "secret-telegram-token"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    respx.post(url).mock(return_value=httpx.Response(401, json={"ok": False, "description": token}))
    message = EmailMessage("message-1", "thread-1", "alice@example.com", "Hello", "Body")

    async with httpx.AsyncClient() as client:
        output = TelegramOutput(token, "123", client)
        with pytest.raises(ProviderError) as exc_info:
            await output.send(message, "Summary")

    error = str(exc_info.value)
    assert error == "Telegram send failed with HTTP 401"
    assert token not in error
    assert url not in error


@respx.mock
async def test_telegram_digest_lists_each_held_email() -> None:
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    items = [
        DigestItem("m1", "t1", "Techcombank <offers@techcombank.com>", "Trả góp 0%"),
        DigestItem("m2", "t2", "news@shop.com", "Tuần này", summary="**Giảm 50%** cho giày."),
    ]

    async with httpx.AsyncClient() as client:
        await TelegramOutput("test-token", "123", client).send_digest(items)

    assert route.call_count == 1
    payload = json.loads(route.calls.last.request.content)
    assert payload == {
        "chat_id": "123",
        "text": (
            "📬 Email quảng cáo hôm nay (2)\n\n"
            "1. Techcombank — Trả góp 0%\n\n"
            "2. news@shop.com — Tuần này\n   Giảm 50% cho giày."
        ),
    }


@respx.mock
async def test_telegram_digest_splits_long_lists_between_items() -> None:
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    items = [
        DigestItem(f"m{index}", "", "shop@example.com", f"Sale {index}", summary="x" * 300)
        for index in range(40)
    ]

    async with httpx.AsyncClient() as client:
        await TelegramOutput("test-token", "123", client).send_digest(items)

    texts = [json.loads(call.request.content)["text"] for call in route.calls]
    assert len(texts) > 1
    assert all(len(text) <= 4096 for text in texts)
    combined = "\n\n".join(texts)
    assert all(f"{index + 1}. shop@example.com — Sale {index}" in combined for index in range(40))


@respx.mock
async def test_telegram_digest_failure_does_not_expose_token() -> None:
    token = "secret-telegram-token"
    respx.post(f"https://api.telegram.org/bot{token}/sendMessage").mock(
        return_value=httpx.Response(500, text=token)
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderError) as exc_info:
            await TelegramOutput(token, "123", client).send_digest(
                [DigestItem("m1", "t1", "shop@example.com", "Sale")]
            )

    assert str(exc_info.value) == "Telegram digest failed with HTTP 500"
    assert token not in str(exc_info.value)
