import httpx
import pytest
import respx

from whisp.chat.web import WebFetcher, WebFetchError

PUBLIC = "93.184.216.34"


def resolver_for(mapping: dict[str, str]):
    async def resolve(host: str, port: int) -> list[str]:
        return [mapping.get(host, PUBLIC)]

    return resolve


@respx.mock
async def test_fetches_public_page_as_text() -> None:
    respx.get("https://example.com/offer").mock(
        return_value=httpx.Response(
            200, html="<h1>Sale</h1><p>50% off</p>", headers={"content-type": "text/html"}
        )
    )

    async with httpx.AsyncClient() as client:
        result = await WebFetcher(client, resolver_for({})).fetch("https://example.com/offer")

    assert "Sale" in result.text and "50% off" in result.text


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"],
)
async def test_private_addresses_are_blocked(address: str) -> None:
    async with httpx.AsyncClient() as client:
        fetcher = WebFetcher(client, resolver_for({"internal.test": address}))
        with pytest.raises(WebFetchError, match="private or internal"):
            await fetcher.fetch("http://internal.test/status")


@respx.mock
async def test_redirect_to_private_address_is_blocked() -> None:
    respx.get("https://example.com/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://metadata.test/latest"})
    )
    metadata = respx.get("http://metadata.test/latest")

    async with httpx.AsyncClient() as client:
        fetcher = WebFetcher(client, resolver_for({"metadata.test": "169.254.169.254"}))
        with pytest.raises(WebFetchError, match="private or internal"):
            await fetcher.fetch("https://example.com/r")

    assert not metadata.called


async def test_non_http_schemes_are_refused() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(WebFetchError, match="http and https"):
            await WebFetcher(client, resolver_for({})).fetch("file:///etc/passwd")


@respx.mock
async def test_oversized_pages_are_refused() -> None:
    respx.get("https://example.com/huge").mock(
        return_value=httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(WebFetchError, match="too large"):
            await WebFetcher(client, resolver_for({})).fetch("https://example.com/huge")
