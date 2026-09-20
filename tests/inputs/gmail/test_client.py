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
