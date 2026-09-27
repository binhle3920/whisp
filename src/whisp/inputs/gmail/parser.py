import base64
from collections.abc import Iterator
from typing import Any

from whisp.core.models import Attachment, EmailCategory, EmailMessage, EmailSummary
from whisp.text import html_links, html_to_text

# Gmail inbox-tab labels mapped to core categories. Tabs without a mapping stay
# uncategorized and are left to the processor.
CATEGORY_LABELS = {
    "CATEGORY_PROMOTIONS": EmailCategory.PROMOTIONAL,
}


def _decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _walk(part: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield a MIME part and all of its descendants, depth first."""
    yield part
    for child in part.get("parts", []):
        yield from _walk(child)


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("payload", {}).get("headers", [])
    }


def _find_bodies(root: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    plain: list[str] = []
    html: list[str] = []
    links: list[str] = []
    for part in _walk(root):
        data = part.get("body", {}).get("data")
        # A part with a filename is an attachment even when it is text/plain or text/html.
        if not data or part.get("filename"):
            continue
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            plain.append(_decode(data))
        elif mime_type == "text/html":
            raw = _decode(data)
            html.append(html_to_text(raw))
            links.extend(html_links(raw))
    return plain, html, links


def _find_attachments(root: dict[str, Any]) -> tuple[Attachment, ...]:
    return tuple(
        Attachment(
            id=part["body"]["attachmentId"],
            filename=part["filename"],
            mime_type=part.get("mimeType", "application/octet-stream"),
            size=int(part["body"].get("size", 0)),
        )
        for part in _walk(root)
        if part.get("filename") and part.get("body", {}).get("attachmentId")
    )


def _category(labels: list[str]) -> EmailCategory | None:
    return next((CATEGORY_LABELS[label] for label in labels if label in CATEGORY_LABELS), None)


def parse_message(payload: dict[str, Any], *, max_chars: int) -> EmailMessage:
    headers = _headers(payload)
    plain, html, links = _find_bodies(payload.get("payload", {}))
    body = "\n\n".join(part.strip() for part in (plain or html) if part.strip())
    # HTML emails hide their link targets behind anchor text; list them so the
    # assistant can see (and is allowed to fetch) them.
    hidden = [link for link in dict.fromkeys(links) if link not in body]
    if hidden:
        body += "\n\nLinks:\n" + "\n".join(hidden)
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
        category=_category(payload.get("labelIds", [])),
        attachments=_find_attachments(payload.get("payload", {})),
    )


def parse_summary(payload: dict[str, Any]) -> EmailSummary:
    headers = _headers(payload)
    return EmailSummary(
        id=payload["id"],
        sender=headers.get("from", "Unknown sender"),
        subject=headers.get("subject", "(no subject)"),
        date=headers.get("date", ""),
        snippet=payload.get("snippet", ""),
    )
