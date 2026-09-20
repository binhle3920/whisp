import asyncio
import logging

from whisp.core.errors import SafeWhispError, safe_error_message
from whisp.core.models import PollResult
from whisp.core.store import Store
from whisp.inputs.base import BaseEmailInput, InputCursorExpired
from whisp.outputs.base import BaseNotificationOutput
from whisp.processors.base import BaseEmailProcessor

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.store = store
        self.input = input_source
        self.processor = processor
        self.output = output
        self.max_messages = max_messages
        self.email_max_chars = email_max_chars
        self._lock = asyncio.Lock()

    async def run_once(self, *, backfill: bool = False) -> PollResult:
        async with self._lock:
            run_id = self.store.start_run()
            cursor = self.store.get("history_id")
            try:
                if cursor is None:
                    next_cursor = await self.input.current_cursor()
                    ids = await self.input.recent_message_ids(self.max_messages) if backfill else []
                    initialized = True
                else:
                    try:
                        ids, next_cursor = await self.input.changes(cursor)
                    except InputCursorExpired:
                        self.store.set("history_id", await self.input.current_cursor())
                        logger.warning(
                            "Input cursor expired; resumed from the provider's current state"
                        )
                        result = PollResult(initialized=True)
                        self._finish(run_id, result)
                        return result
                    initialized = False

                discovered = len(ids)
                # Messages already delivered in an earlier run are skipped without
                # consuming budget, so the batch limit applies to the work that is
                # actually left. Otherwise a re-read of the same range would refill
                # the batch with skips and never reach the tail.
                outstanding = [
                    message_id for message_id in ids if not self.store.is_processed(message_id)
                ]
                skipped = discovered - len(outstanding)
                # Truncating means the tail of this history range is not processed in
                # this run. Hold the cursor back so those messages are rediscovered;
                # advancing past them would drop them silently.
                pending = max(0, len(outstanding) - self.max_messages)
                if pending:
                    outstanding = outstanding[: self.max_messages]
                    logger.info(
                        "Discovered %d messages, processing %d this run; "
                        "%d deferred to the next run",
                        discovered,
                        len(outstanding),
                        pending,
                    )
                notified = failed = 0
                last_error: str | None = None
                for message_id in reversed(outstanding) if backfill else outstanding:
                    try:
                        message = await self.input.fetch(message_id, max_chars=self.email_max_chars)
                        processed_text = await self.processor.process(message)
                        await self.output.send(message, processed_text)
                        self.store.mark_processed(message)
                        notified += 1
                    except Exception as exc:
                        failed += 1
                        last_error = safe_error_message(exc)
                        logger.error(
                            "Failed to process input message %s: %s",
                            message_id,
                            safe_error_message(exc),
                        )

                result = PollResult(discovered, notified, skipped, failed, initialized, pending)
                # Only advance once the whole range is accounted for: any failure or
                # any deferred message means next_cursor covers unprocessed mail.
                if failed == 0 and pending == 0:
                    self.store.set("history_id", next_cursor)
                self._finish(run_id, result, error=last_error)
                return result
            except Exception as exc:
                error = safe_error_message(exc)
                self.store.finish_run(
                    run_id, discovered=0, notified=0, skipped=0, failed=1, error=error
                )
                if isinstance(exc, SafeWhispError):
                    raise
                raise SafeWhispError(error) from None

    def _finish(self, run_id: int, result: PollResult, *, error: str | None = None) -> None:
        self.store.finish_run(
            run_id,
            discovered=result.discovered,
            notified=result.notified,
            skipped=result.skipped,
            failed=result.failed,
            error=error,
        )
