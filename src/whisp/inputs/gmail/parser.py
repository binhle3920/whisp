import base64
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


def _find_bodies(part: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    plain: list[str] = []
    html: list[str] = []
    links: list[str] = []
    mime_type = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    # A part with a filename is an attachment even when it is text/plain or text/html.
    if data and not part.get("filename"):
        if mime_type == "text/plain":
            plain.append(_decode(data))
        elif mime_type == "text/html":
            raw = _decode(data)
            html.append(html_to_text(raw))
            links.extend(html_links(raw))
    for child in part.get("parts", []):
        child_plain, child_html, child_links = _find_bodies(child)
        plain.extend(child_plain)
        html.extend(child_html)
        links.extend(child_links)
    return plain, html, links


def _find_attachments(part: dict[str, Any]) -> list[Attachment]:
    found: list[Attachment] = []
    body = part.get("body", {})
    if part.get("filename") and body.get("attachmentId"):
        found.append(
            Attachment(
                id=body["attachmentId"],
                filename=part["filename"],
                mime_type=part.get("mimeType", "application/octet-stream"),
                size=int(body.get("size", 0)),
            )
        )
    for child in part.get("parts", []):
        found.extend(_find_attachments(child))
    return found


def _category(labels: list[str]) -> EmailCategory | None:
    return next((CATEGORY_LABELS[label] for label in labels if label in CATEGORY_LABELS), None)


def parse_message(payload: dict[str, Any], *, max_chars: int) -> EmailMessage:
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("payload", {}).get("headers", [])
    }
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
        attachments=tuple(_find_attachments(payload.get("payload", {}))),
    )


def parse_summary(payload: dict[str, Any]) -> EmailSummary:
    headers = {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("payload", {}).get("headers", [])
    }
    return EmailSummary(
        id=payload["id"],
        sender=headers.get("from", "Unknown sender"),
        subject=headers.get("subject", "(no subject)"),
        date=headers.get("date", ""),
        snippet=payload.get("snippet", ""),
    )
