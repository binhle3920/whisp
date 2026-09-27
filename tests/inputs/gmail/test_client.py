import httpx
import pytest
import respx

from whisp.core.errors import ProviderError
from whisp.inputs.gmail.client import GmailInput


class FakeAuth:
    async def access_token(self) -> str:
        return "secret-oauth-token"


@respx.mock
async def test_gmail_failure_does_not_expose_oauth_token_or_response() -> None:
    response_secret = "confidential provider response"
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile").mock(
        return_value=httpx.Response(401, text=response_secret)
    )

    async with httpx.AsyncClient() as client:
        gmail = GmailInput(FakeAuth(), client)  # type: ignore[arg-type]
        with pytest.raises(ProviderError) as exc_info:
            await gmail.current_cursor()

    error = str(exc_info.value)
    assert error == "Gmail request failed with HTTP 401"
    assert "secret-oauth-token" not in error
    assert response_secret not in error


BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


@respx.mock
async def test_search_returns_summaries_from_metadata() -> None:
    listing = respx.get(f"{BASE}/messages").mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "a1"}]})
    )
    respx.get(f"{BASE}/messages/a1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "a1",
                "snippet": "Please find the contract",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <alice@example.com>"},
                        {"name": "Subject", "value": "Contract"},
                        {"name": "Date", "value": "Fri, 25 Sep 2026 10:00:00 +0700"},
                    ]
                },
            },
        )
    )

    async with httpx.AsyncClient() as client:
        results = await GmailInput(FakeAuth(), client).search(  # type: ignore[arg-type]
            "subject:contract", limit=50
        )

    assert [(r.id, r.subject, r.snippet) for r in results] == [
        ("a1", "Contract", "Please find the contract")
    ]
    params = listing.calls.last.request.url.params
    assert params["q"] == "subject:contract"
    assert params["maxResults"] == "10"


@respx.mock
async def test_download_attachment_decodes_base64() -> None:
    respx.get(f"{BASE}/messages/m1/attachments/att_1").mock(
        return_value=httpx.Response(200, json={"size": 5, "data": "aGVsbG8"})
    )

    async with httpx.AsyncClient() as client:
        data = await GmailInput(FakeAuth(), client).download_attachment(  # type: ignore[arg-type]
            "m1", "att_1"
        )

    assert data == b"hello"


async def test_ids_that_could_alter_the_request_path_are_rejected() -> None:
    async with httpx.AsyncClient() as client:
        gmail = GmailInput(FakeAuth(), client)  # type: ignore[arg-type]
        with pytest.raises(ProviderError, match="invalid id"):
            await gmail.fetch("../drafts", max_chars=1000)
        with pytest.raises(ProviderError, match="invalid id"):
            await gmail.download_attachment("m1", "a/../b")
