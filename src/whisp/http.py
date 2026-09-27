from typing import Any

import httpx

from whisp.core.errors import ProviderError


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    operation: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Send one request and return its JSON object body.

    Every failure becomes a ProviderError raised `from None`: httpx exceptions carry the
    request URL, and some provider URLs (Telegram's) contain credentials.
    """
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.HTTPError:
        raise ProviderError(provider, operation) from None
    if response.is_error:
        raise ProviderError(provider, operation, status_code=response.status_code)
    try:
        data = response.json()
    except ValueError:
        raise ProviderError(provider, f"{operation} response decoding") from None
    if not isinstance(data, dict):
        raise ProviderError(provider, f"{operation} response decoding")
    return data
