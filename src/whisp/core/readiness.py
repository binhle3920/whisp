import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime

from whisp.core.errors import safe_error_message
from whisp.core.pipeline import Pipeline


class ReadinessMonitor:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, object] = {
            "ready": False,
            "checked_at": None,
            "checks": {},
        }

    def snapshot(self) -> dict[str, object]:
        return deepcopy(self._snapshot)

    async def refresh(self) -> dict[str, object]:
        async with self._lock:
            checked_at = datetime.now(UTC).isoformat()
            checks = await asyncio.gather(
                self._run_check("store", self._check_store, checked_at),
                self._run_check("input", self.pipeline.input.check, checked_at),
                self._run_check("output", self.pipeline.output.check, checked_at),
            )
            check_map = {name: result for name, result in checks}
            self._snapshot = {
                "ready": all(bool(result["ok"]) for result in check_map.values()),
                "checked_at": checked_at,
                "checks": check_map,
            }
            return self.snapshot()

    async def _check_store(self) -> None:
        await asyncio.to_thread(self.pipeline.store.status)

    async def _run_check(
        self,
        name: str,
        check: Callable[[], Awaitable[None]],
        checked_at: str,
    ) -> tuple[str, dict[str, object]]:
        try:
            await check()
        except Exception as exc:
            return name, {
                "ok": False,
                "checked_at": checked_at,
                "error": safe_error_message(exc),
            }
        return name, {"ok": True, "checked_at": checked_at, "error": None}
