from whisp.core.models import EmailMessage
from whisp.core.pipeline import Pipeline
from whisp.core.store import Store
from whisp.inputs.base import BaseEmailInput
from whisp.outputs.base import BaseNotificationOutput
from whisp.processors.base import BaseEmailProcessor


class FakeInput(BaseEmailInput):
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def current_cursor(self) -> str:
        return "100"

    async def recent_message_ids(self, limit: int) -> list[str]:
        return self.ids[:limit]

    async def changes(self, cursor: str) -> tuple[list[str], str]:
        return self.ids, "101"

    async def fetch(self, message_id: str, *, max_chars: int) -> EmailMessage:
        return EmailMessage(
            id=message_id,
            thread_id="thread-1",
            sender="alice@example.com",
            subject="Review",
            body="Please review by Friday"[:max_chars],
        )


class FakeProcessor(BaseEmailProcessor):
    async def process(self, message: EmailMessage) -> str:
        return f"Summary of {message.subject}"


class RecordingOutput(BaseNotificationOutput):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def check(self) -> None:
        return None

    async def send(self, message: EmailMessage, processed_text: str) -> None:
        self.sent.append((message.id, processed_text))


async def test_initializes_then_delivers_and_deduplicates(tmp_path) -> None:
    input_source = FakeInput()
    output = RecordingOutput()
    store = Store(tmp_path / "whisp.db")
    pipeline = Pipeline(
        store=store,
        input_source=input_source,
        processor=FakeProcessor(),
        output=output,
        max_messages=25,
        email_max_chars=12_000,
    )

    first = await pipeline.run_once()
    assert first.initialized
    assert store.get("history_id") == "100"

    input_source.ids = ["message-1"]
    second = await pipeline.run_once()
    assert second.notified == 1
    assert output.sent == [("message-1", "Summary of Review")]
    assert store.get("history_id") == "101"

    third = await pipeline.run_once()
    assert third.skipped == 1
    assert len(output.sent) == 1
