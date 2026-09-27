import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

import httpx

from whisp.chat.documents import UnsupportedDocument, extract, limit_text
from whisp.chat.models import ToolResult
from whisp.core.errors import SafeWhispError
from whisp.text import html_to_text

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15

Resolver = Callable[[str, int], Awaitable[list[str]]]


class WebFetchError(SafeWhispError):
    """A web page was refused or could not be fetched."""


def normalize_url(url: str) -> str:
    """Canonical form used to compare a requested URL with the allowed set."""
    parsed = httpx.URL(url.strip())
    return str(parsed.copy_with(fragment=None))


async def _system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class WebFetcher:
    """Fetches pages for the assistant without letting it reach private networks.

    Every hop (including redirects) must resolve only to public addresses, so a link in
    an email cannot make Whisp call its own API on 127.0.0.1 or a cloud metadata service.
    The address is checked before the request rather than pinned into it, so a DNS
    answer that changes between the two (DNS rebinding) is a known residual gap; it is
    accepted because a URL must already appear in an email or the user's message.
    """

    def __init__(self, *, client: httpx.AsyncClient, resolver: Resolver | None = None) -> None:
        self.client = client
        self.resolver = resolver or _system_resolver

    async def fetch(self, url: str) -> ToolResult:
        current = httpx.URL(normalize_url(url))
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_destination(current)
            try:
                async with self.client.stream(
                    "GET",
                    current,
                    follow_redirects=False,
                    timeout=TIMEOUT_SECONDS,
                    headers={"User-Agent": "Whisp/0.1 (personal email assistant)"},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise WebFetchError("Redirect without a destination")
                        current = current.join(location)
                        continue
                    if response.status_code >= 400:
                        raise WebFetchError(f"Page returned HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "")
                    body = await self._read_limited(response)
            except httpx.HTTPError:
                raise WebFetchError("Page could not be fetched") from None
            return self._to_result(str(current), content_type, body)
        raise WebFetchError("Too many redirects")

    async def _check_destination(self, url: httpx.URL) -> None:
        if url.scheme not in ("http", "https") or not url.host:
            raise WebFetchError("Only http and https links can be opened")
        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            addresses = await self.resolver(url.host, port)
        except OSError:
            raise WebFetchError("Host could not be resolved") from None
        if not addresses or not all(_is_public(address) for address in addresses):
            raise WebFetchError("Links to private or internal addresses are blocked")

    async def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise WebFetchError("Page is too large (limit 2 MB)")
            chunks.append(chunk)
        return b"".join(chunks)

    def _to_result(self, url: str, content_type: str, body: bytes) -> ToolResult:
        kind = content_type.split(";")[0].strip().lower()
        if kind in ("text/html", "application/xhtml+xml", ""):
            text = limit_text(html_to_text(body.decode("utf-8", errors="replace")))
            return ToolResult(text=f"URL: {url}\n\n{text}")
        try:
            return extract(url.rsplit("/", 1)[-1] or "page", kind, body)
        except UnsupportedDocument as exc:
            raise WebFetchError(str(exc)) from None
