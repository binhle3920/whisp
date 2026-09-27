from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRequest:
    """One inbound user message, independent of the chat provider it arrived through."""

    chat_id: str
    text: str
    # Set when the user replied to a notification that was linked to an email.
    reply_to_email_id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    text: str
    # (mime_type, data) images the model should see, e.g. an image attachment.
    images: tuple[tuple[str, bytes], ...] = ()
