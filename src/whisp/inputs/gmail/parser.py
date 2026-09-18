import base64
import re
from html import unescape
from typing import Any

from whisp.core.models import EmailMessage


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _find_bodies(part: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    html: list[str] = []
    mime_type = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and mime_type == "text/plain":
        plain.append(_decode(data))
    elif data and mime_type == "text/html":
        html.append(_html_to_text(_decode(data)))
    for child in part.get("parts", []):
        child_plain, child_html = _find_bodies(child)
        plain.extend(child_plain)
        html.extend(child_html)
    return plain, html


def parse_message(payload: dict[str, Any], *, max_chars: int) -> EmailMessage:
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("payload", {}).get("headers", [])
    }
    plain, html = _find_bodies(payload.get("payload", {}))
    body = "\n\n".join(part.strip() for part in (plain or html) if part.strip())
    if not body:
        body = payload.get("snippet", "")
    body = body.strip()
    if len(body) > max_chars:
        half = (max_chars - 24) // 2
        body = f"{body[:half]}\n[... truncated ...]\n{body[-half:]}"
    return EmailMessage(
        id=payload["id"],
        thread_id=payload.get("threadId", ""),
        sender=headers.get("from", "Unknown sender"),
        subject=headers.get("subject", "(no subject)"),
        body=body or "(empty message)",
        internal_date=payload.get("internalDate"),
    )

