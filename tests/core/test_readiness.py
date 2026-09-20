from types import SimpleNamespace

from whisp.core.readiness import ReadinessMonitor
from whisp.core.store import Store


class CountingCheck:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def check(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


async def test_readiness_refreshes_dependencies_and_caches_snapshot(tmp_path) -> None:
    input_check = CountingCheck()
    output_check = CountingCheck()
    pipeline = SimpleNamespace(
        store=Store(tmp_path / "whisp.db"),
        input=input_check,
        output=output_check,
    )
    monitor = ReadinessMonitor(pipeline)  # type: ignore[arg-type]

    initial = monitor.snapshot()
    refreshed = await monitor.refresh()
    cached = monitor.snapshot()

    assert initial == {"ready": False, "checked_at": None, "checks": {}}
    assert refreshed["ready"] is True
    assert refreshed == cached
    assert input_check.calls == 1
    assert output_check.calls == 1
    assert refreshed["checks"]["store"]["ok"] is True
    assert refreshed["checks"]["input"]["checked_at"] == refreshed["checked_at"]


async def test_readiness_sanitizes_dependency_failures(tmp_path) -> None:
    secret = "secret-provider-response"
    pipeline = SimpleNamespace(
        store=Store(tmp_path / "whisp.db"),
        input=CountingCheck(RuntimeError(secret)),
        output=CountingCheck(),
    )
    monitor = ReadinessMonitor(pipeline)  # type: ignore[arg-type]

    snapshot = await monitor.refresh()

    assert snapshot["ready"] is False
    assert snapshot["checks"]["input"]["error"] == "Unexpected RuntimeError"
    assert secret not in str(snapshot)
