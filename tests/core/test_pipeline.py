import logging

import pytest

from whisp.core.errors import SafeWhispError
from whisp.core.models import DigestItem, EmailCategory, EmailMessage, ProcessedEmail
from whisp.core.pipeline import Pipeline
from whisp.core.store import Store
from whisp.inputs.base import BaseEmailInput
from whisp.outputs.base import BaseNotificationOutput
from whisp.processors.base import BaseEmailProcessor


class FakeInput(BaseEmailInput):
    def __init__(self, promotional: set[str] | None = None) -> None:
        self.ids: list[str] = []
        self.promotional = promotional or set()

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
            category=EmailCategory.PROMOTIONAL if message_id in self.promotional else None,
        )


class FakeProcessor(BaseEmailProcessor):
    def __init__(self, marketing: set[str] | None = None) -> None:
        self.marketing = marketing or set()
        self.processed: list[str] = []

    async def process(self, message: EmailMessage) -> ProcessedEmail:
        self.processed.append(message.id)
        return ProcessedEmail(
            text=f"Summary of {message.subject}", marketing=message.id in self.marketing
        )


class LeakyProcessor(BaseEmailProcessor):
    async def process(self, message: EmailMessage) -> ProcessedEmail:
        raise RuntimeError(message.body)


class LeakyInput(FakeInput):
    async def changes(self, cursor: str) -> tuple[list[str], str]:
        raise RuntimeError("secret-oauth-token")


class RecordingOutput(BaseNotificationOutput):
    def __init__(self, fail_digest: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.digests: list[list[DigestItem]] = []
        self.fail_digest = fail_digest

    async def check(self) -> None:
        return None

    async def send(self, message: EmailMessage, processed_text: str) -> None:
        self.sent.append((message.id, processed_text))

    async def send_digest(self, items: list[DigestItem]) -> None:
        if self.fail_digest:
            raise RuntimeError("digest delivery failed")
        self.digests.append(items)


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


async def test_pipeline_sanitizes_message_failure_logs(tmp_path, caplog) -> None:
    input_source = FakeInput()
    input_source.ids = ["message-1"]
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = Pipeline(
        store=store,
        input_source=input_source,
        processor=LeakyProcessor(),
        output=RecordingOutput(),
        max_messages=25,
        email_max_chars=12_000,
    )

    with caplog.at_level(logging.ERROR):
        result = await pipeline.run_once()

    assert result.failed == 1
    assert "Please review by Friday" not in caplog.text
    assert "Unexpected RuntimeError" in caplog.text


async def test_pipeline_sanitizes_stored_and_raised_errors(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = Pipeline(
        store=store,
        input_source=LeakyInput(),
        processor=FakeProcessor(),
        output=RecordingOutput(),
        max_messages=25,
        email_max_chars=12_000,
    )

    with pytest.raises(SafeWhispError) as exc_info:
        await pipeline.run_once()

    assert str(exc_info.value) == "Unexpected RuntimeError"
    assert store.status()["last_run"]["error"] == "Unexpected RuntimeError"
    assert "secret-oauth-token" not in str(exc_info.value)


async def test_high_volume_changes_are_processed_across_runs(tmp_path) -> None:
    """A burst larger than max_messages must drain fully, not be truncated away."""
    input_source = FakeInput()
    input_source.ids = [f"message-{index}" for index in range(100)]
    output = RecordingOutput()
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = Pipeline(
        store=store,
        input_source=input_source,
        processor=FakeProcessor(),
        output=output,
        max_messages=25,
        email_max_chars=12_000,
    )

    first = await pipeline.run_once()
    assert first.discovered == 100
    assert first.notified == 25
    assert first.pending == 75
    # The cursor must not move past messages this run did not process.
    assert store.get("history_id") == "100"

    # Drain the rest. The provider keeps returning the same range until the
    # cursor advances, and already-delivered messages are skipped by dedup.
    for _ in range(3):
        await pipeline.run_once()

    delivered = {message_id for message_id, _ in output.sent}
    assert len(delivered) == 100
    assert store.get("history_id") == "101"

    final = await pipeline.run_once()
    assert final.notified == 0
    assert final.pending == 0


async def test_cursor_is_held_back_until_batch_is_fully_processed(tmp_path) -> None:
    input_source = FakeInput()
    input_source.ids = ["message-1", "message-2", "message-3"]
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = Pipeline(
        store=store,
        input_source=input_source,
        processor=FakeProcessor(),
        output=RecordingOutput(),
        max_messages=2,
        email_max_chars=12_000,
    )

    result = await pipeline.run_once()
    assert result.discovered == 3
    assert result.notified == 2
    assert result.pending == 1
    assert store.get("history_id") == "100"

    final = await pipeline.run_once()
    assert final.notified == 1
    assert final.pending == 0
    assert store.get("history_id") == "101"


def make_pipeline(
    store: Store,
    input_source: FakeInput,
    processor: FakeProcessor,
    output: RecordingOutput,
    *,
    digest_enabled: bool = True,
) -> Pipeline:
    return Pipeline(
        store=store,
        input_source=input_source,
        processor=processor,
        output=output,
        max_messages=25,
        email_max_chars=12_000,
        digest_enabled=digest_enabled,
    )


async def test_marketing_is_held_for_digest_and_other_mail_is_sent(tmp_path) -> None:
    input_source = FakeInput(promotional={"promo"})
    input_source.ids = ["promo", "newsletter", "personal"]
    processor = FakeProcessor(marketing={"newsletter"})
    output = RecordingOutput()
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = make_pipeline(store, input_source, processor, output)

    result = await pipeline.run_once()

    assert result.queued == 2
    assert result.notified == 1
    assert output.sent == [("personal", "Summary of Review")]
    # Category-flagged mail never reaches the processor.
    assert processor.processed == ["newsletter", "personal"]
    # Queued mail counts as handled, so the cursor advances and it is not re-fetched.
    assert store.get("history_id") == "101"
    assert (await pipeline.run_once()).skipped == 3
    assert [(item.message_id, item.summary) for item in store.pending_digest()] == [
        ("promo", None),
        ("newsletter", "Summary of Review"),
    ]


async def test_send_digest_delivers_pending_once(tmp_path) -> None:
    input_source = FakeInput(promotional={"promo-1", "promo-2"})
    input_source.ids = ["promo-1", "promo-2"]
    output = RecordingOutput()
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = make_pipeline(store, input_source, FakeProcessor(), output)
    await pipeline.run_once()

    assert await pipeline.send_digest() == 2
    assert [item.message_id for item in output.digests[0]] == ["promo-1", "promo-2"]
    assert await pipeline.send_digest() == 0
    assert len(output.digests) == 1
    assert store.status()["digest_pending"] == 0


async def test_failed_digest_keeps_messages_pending(tmp_path) -> None:
    input_source = FakeInput(promotional={"promo"})
    input_source.ids = ["promo"]
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = make_pipeline(store, input_source, FakeProcessor(), RecordingOutput(True))
    await pipeline.run_once()

    with pytest.raises(SafeWhispError) as exc_info:
        await pipeline.send_digest()

    assert str(exc_info.value) == "Unexpected RuntimeError"
    assert [item.message_id for item in store.pending_digest()] == ["promo"]


async def test_disabled_digest_sends_marketing_immediately(tmp_path) -> None:
    input_source = FakeInput(promotional={"promo"})
    input_source.ids = ["promo", "newsletter"]
    output = RecordingOutput()
    store = Store(tmp_path / "whisp.db")
    store.set("history_id", "100")
    pipeline = make_pipeline(
        store,
        input_source,
        FakeProcessor(marketing={"newsletter"}),
        output,
        digest_enabled=False,
    )

    result = await pipeline.run_once()

    assert result.queued == 0
    assert [message_id for message_id, _ in output.sent] == ["promo", "newsletter"]
    assert store.pending_digest() == []
