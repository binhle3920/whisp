import json
from datetime import datetime, time
from types import SimpleNamespace

from whisp.app import _send_digest_if_due, health, readiness, status
from whisp.core.store import Store


class StubReadiness:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.calls = 0

    def snapshot(self) -> dict[str, object]:
        self.calls += 1
        return {
            "ready": self.ready,
            "checked_at": "2026-09-20T00:00:00+00:00",
            "checks": {},
        }


def request_with_state(**state):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state)))


async def test_health_is_lightweight() -> None:
    request = request_with_state(
        settings=SimpleNamespace(poller_enabled=True),
        readiness=StubReadiness(ready=True),
    )

    result = await health(request)  # type: ignore[arg-type]

    assert result == {"ok": True, "poller_enabled": True}
    assert request.app.state.readiness.calls == 0


async def test_readyz_returns_cached_snapshot_with_service_status() -> None:
    ready_monitor = StubReadiness(ready=True)
    ready_response = await readiness(  # type: ignore[arg-type]
        request_with_state(readiness=ready_monitor)
    )
    unavailable_response = await readiness(  # type: ignore[arg-type]
        request_with_state(readiness=StubReadiness(ready=False))
    )

    assert ready_response.status_code == 200
    assert json.loads(ready_response.body)["ready"] is True
    assert unavailable_response.status_code == 503
    assert json.loads(unavailable_response.body)["ready"] is False
    assert ready_monitor.calls == 1


async def test_status_combines_store_and_cached_readiness(tmp_path) -> None:
    store = Store(tmp_path / "whisp.db")
    monitor = StubReadiness(ready=True)

    result = await status(  # type: ignore[arg-type]
        request_with_state(
            store=store,
            readiness=monitor,
            settings=SimpleNamespace(git_commit="0c181f2abc"),
        )
    )

    assert result["git_commit"] == "0c181f2abc"
    assert result["processed_messages"] == 0
    assert result["queue"] == {
        "available": False,
        "pending": 0,
        "retrying": 0,
        "dead_letter": 0,
    }
    assert result["readiness"]["ready"] is True


class CountingPipeline:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.digests = 0

    async def send_digest(self) -> int:
        self.digests += 1
        return 0


async def test_digest_is_sent_once_per_day_after_digest_time(tmp_path) -> None:
    pipeline = CountingPipeline(Store(tmp_path / "whisp.db"))
    app = SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(digest_at=time(23, 0)), pipeline=pipeline)
    )

    await _send_digest_if_due(app, datetime(2026, 9, 25, 22, 59))  # type: ignore[arg-type]
    assert pipeline.digests == 0

    await _send_digest_if_due(app, datetime(2026, 9, 25, 23, 0))  # type: ignore[arg-type]
    await _send_digest_if_due(app, datetime(2026, 9, 25, 23, 30))  # type: ignore[arg-type]
    assert pipeline.digests == 1

    await _send_digest_if_due(app, datetime(2026, 9, 26, 23, 5))  # type: ignore[arg-type]
    assert pipeline.digests == 2
