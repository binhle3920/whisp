import asyncio
import logging

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
            return await self._run_once(backfill=backfill)

    async def _run_once(self, *, backfill: bool) -> PollResult:
        run_id = self.store.start_run()
        cursor = self.store.get("history_id")
        try:
            if cursor is None:
                next_cursor = await self.input.current_cursor()
                ids = (
                    await self.input.recent_message_ids(self.max_messages) if backfill else []
                )
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

            ids = ids[: self.max_messages]
            discovered = len(ids)
            notified = skipped = failed = 0
            for message_id in reversed(ids) if backfill else ids:
                if self.store.is_processed(message_id):
                    skipped += 1
                    continue
                try:
                    message = await self.input.fetch(
                        message_id, max_chars=self.email_max_chars
                    )
                    processed_text = await self.processor.process(message)
                    await self.output.send(message, processed_text)
                    self.store.mark_processed(message)
                    notified += 1
                except Exception:
                    failed += 1
                    logger.exception("Failed to process input message %s", message_id)

            result = PollResult(discovered, notified, skipped, failed, initialized)
            if failed == 0:
                self.store.set("history_id", next_cursor)
            self._finish(run_id, result)
            return result
        except Exception as exc:
            self.store.finish_run(
                run_id, discovered=0, notified=0, skipped=0, failed=1, error=str(exc)
            )
            raise

    def _finish(self, run_id: int, result: PollResult) -> None:
        self.store.finish_run(
            run_id,
            discovered=result.discovered,
            notified=result.notified,
            skipped=result.skipped,
            failed=result.failed,
        )
