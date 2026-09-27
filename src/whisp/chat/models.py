from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatRequest:
    """One inbound user message, independent of the chat provider it arrived through."""

    chat_id: str
    text: str
    # Set when the user replied to a notification that was linked to an email.
    reply_to_email_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # Raw JSON from the model; parsed and validated by the tool that receives it.
    arguments: str


@dataclass(frozen=True)
class ChatCompletion:
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    text: str
    # (mime_type, data) images the model should see, e.g. an image attachment.
    images: tuple[tuple[str, bytes], ...] = field(default_factory=tuple)
