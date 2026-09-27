import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Literal

from whisp.core.errors import safe_error_message, sanitized_errors
from whisp.core.models import EmailCategory, PollResult
from whisp.core.store import CURSOR_KEY, LAST_DIGEST_KEY, Store
from whisp.inputs.base import BaseEmailInput, InputCursorExpired
from whisp.outputs.base import BaseNotificationOutput
from whisp.processors.base import BaseEmailProcessor

logger = logging.getLogger(__name__)


def next_digest_at(now: datetime, at: time, last_digest_date: str | None) -> datetime:
    """When the next digest goes out: today unless today's has already been sent."""
    today = now.date()
    sent_today = now.time() >= at and last_digest_date == today.isoformat()
    day = today + timedelta(days=1) if sent_today else today
    return datetime.combine(day, at, tzinfo=now.tzinfo)


class Pipeline:
    def __init__(
        self,
        *,
        store: Store,
        input_source: BaseEmailInput,
        processor: BaseEmailProcessor,
        output: BaseNotificationOutput,
        max_messages: int,
        email_max_chars: int,
        digest_enabled: bool = True,
    ) -> None:
        self.store = store
        self.input = input_source
        self.processor = processor
        self.output = output
        self.max_messages = max_messages
        self.email_max_chars = email_max_chars
        self.digest_enabled = digest_enabled
        self._lock = asyncio.Lock()

    async def run_once(self, *, backfill: bool = False) -> PollResult:
        async with self._lock:
            run_id = self.store.start_run()
            try:
                with sanitized_errors():
                    result, error = await self._run(backfill)
            except Exception as exc:
                self.store.finish_run(run_id, PollResult(failed=1), error=str(exc))
                raise
            self.store.finish_run(run_id, result, error=error)
            return result

    async def _run(self, backfill: bool) -> tuple[PollResult, str | None]:
        cursor = self.store.get(CURSOR_KEY)
        if cursor is None:
            next_cursor = await self.input.current_cursor()
            ids = await self.input.recent_message_ids(self.max_messages) if backfill else []
            initialized = True
        else:
            try:
                ids, next_cursor = await self.input.changes(cursor)
            except InputCursorExpired:
                self.store.set(CURSOR_KEY, await self.input.current_cursor())
                logger.warning("Input cursor expired; resumed from the provider's current state")
                return PollResult(initialized=True), None
            initialized = False

        discovered = len(ids)
        # Messages already delivered in an earlier run are skipped without consuming
        # budget, so the batch limit applies to the work that is actually left. Otherwise
        # a re-read of the same range would refill the batch with skips and never reach
        # the tail.
        outstanding = [message_id for message_id in ids if not self.store.is_processed(message_id)]
        skipped = discovered - len(outstanding)
        # Truncating means the tail of this history range is not processed in this run.
        # Hold the cursor back so those messages are rediscovered; advancing past them
        # would drop them silently.
        pending = max(0, len(outstanding) - self.max_messages)
        if pending:
            outstanding = outstanding[: self.max_messages]
            logger.info(
                "Discovered %d messages, processing %d this run; %d deferred to the next run",
                discovered,
                len(outstanding),
                pending,
            )

        notified = failed = queued = 0
        last_error: str | None = None
        for message_id in reversed(outstanding) if backfill else outstanding:
            try:
                outcome = await self._deliver(message_id)
            except Exception as exc:
                failed += 1
                last_error = safe_error_message(exc)
                logger.error("Failed to process input message %s: %s", message_id, last_error)
                continue
            if outcome == "queued":
                queued += 1
            else:
                notified += 1

        # Only advance once the whole range is accounted for: any failure or any deferred
        # message means next_cursor covers unprocessed mail.
        if failed == 0 and pending == 0:
            self.store.set(CURSOR_KEY, next_cursor)
        result = PollResult(
            discovered=discovered,
            notified=notified,
            skipped=skipped,
            failed=failed,
            initialized=initialized,
            pending=pending,
            queued=queued,
        )
        return result, last_error

    async def _deliver(self, message_id: str) -> Literal["notified", "queued"]:
        message = await self.input.fetch(message_id, max_chars=self.email_max_chars)
        # The input's own categorization is trusted first so obvious promotions skip the
        # processor call entirely.
        if self.digest_enabled and message.category is EmailCategory.PROMOTIONAL:
            self.store.queue_digest(message, summary=None)
            return "queued"
        processed = await self.processor.process(message)
        if self.digest_enabled and processed.marketing:
            self.store.queue_digest(message, summary=processed.text)
            return "queued"
        reference = await self.output.send(message, processed.text)
        self.store.mark_processed(message)
        # Lets a chat reply to this notification refer back to the email.
        if reference:
            self.store.link_notification(reference, message.id)
        return "notified"

    async def send_digest(self) -> int:
        """Deliver every held marketing message as one digest; return how many were sent."""
        async with self._lock:
            return await self._send_digest()

    async def send_digest_if_due(self, now: datetime, at: time) -> int | None:
        """Send today's digest once `now` has passed `at`; None when it was not due.

        Compares against a persisted date rather than sleeping until the exact minute, so
        a restart spanning the digest time still sends that day's digest, and never twice.
        """
        async with self._lock:
            today = now.date().isoformat()
            if now.time() < at or self.store.get(LAST_DIGEST_KEY) == today:
                return None
            sent = await self._send_digest()
            self.store.set(LAST_DIGEST_KEY, today)
            return sent

    async def _send_digest(self) -> int:
        with sanitized_errors():
            items = self.store.pending_digest()
            if not items:
                return 0
            await self.output.send_digest(items)
            # Marked only after the output accepts the digest: a crash in between repeats
            # the digest rather than losing it, matching single notifications.
            self.store.mark_digest_sent([item.message_id for item in items])
            return len(items)
