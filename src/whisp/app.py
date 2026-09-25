import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from whisp.config import get_settings
from whisp.core.errors import safe_error_message
from whisp.core.readiness import ReadinessMonitor
from whisp.logging_config import configure_logging
from whisp.runtime import build_pipeline

logger = logging.getLogger(__name__)


async def _poll_forever(app: FastAPI) -> None:
    settings = app.state.settings
    while True:
        try:
            result = await app.state.pipeline.run_once()
            logger.info("Poll complete: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Poll failed; retrying on the next interval")
        await asyncio.sleep(settings.poll_interval_seconds)


async def _send_digest_if_due(app: FastAPI, now: datetime) -> None:
    settings = app.state.settings
    store = app.state.pipeline.store
    today = now.date().isoformat()
    # Compare against a persisted date rather than sleeping until the exact minute, so a
    # restart spanning digest_time still sends that day's digest, and never sends twice.
    if now.time() < settings.digest_at or store.get("last_digest_date") == today:
        return
    sent = await app.state.pipeline.send_digest()
    store.set("last_digest_date", today)
    logger.info("Digest sent with %d messages", sent)


async def _digest_forever(app: FastAPI) -> None:
    settings = app.state.settings
    while True:
        try:
            await _send_digest_if_due(app, datetime.now(settings.zone))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Digest failed; retrying shortly: %s", safe_error_message(exc))
        await asyncio.sleep(60)


async def _check_readiness_forever(app: FastAPI) -> None:
    settings = app.state.settings
    while True:
        try:
            await app.state.readiness.refresh()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Readiness refresh failed: %s", safe_error_message(exc))
        await asyncio.sleep(settings.readiness_check_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    client = httpx.AsyncClient(timeout=30)
    app.state.settings = settings
    app.state.store = None
    app.state.readiness = None
    tasks: list[asyncio.Task] = []
    try:
        pipeline = build_pipeline(settings, client)
        app.state.pipeline = pipeline
        app.state.store = pipeline.store
        app.state.readiness = ReadinessMonitor(pipeline)
        tasks.append(asyncio.create_task(_check_readiness_forever(app)))
        if settings.poller_enabled:
            tasks.append(asyncio.create_task(_poll_forever(app)))
        if settings.digest_enabled:
            tasks.append(asyncio.create_task(_digest_forever(app)))
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await client.aclose()


app = FastAPI(title="Whisp", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def health(request: Request) -> dict[str, object]:
    return {"ok": True, "poller_enabled": request.app.state.settings.poller_enabled}


@app.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    monitor = request.app.state.readiness
    snapshot = (
        monitor.snapshot()
        if monitor is not None
        else {
            "ready": False,
            "checked_at": None,
            "checks": {},
        }
    )
    return JSONResponse(status_code=200 if snapshot["ready"] else 503, content=snapshot)


@app.get("/status")
async def status(request: Request) -> dict[str, object]:
    if request.app.state.store is None:
        raise HTTPException(503, "Whisp is not configured")
    result = request.app.state.store.status()
    result["git_commit"] = request.app.state.settings.git_commit
    monitor = request.app.state.readiness
    result["readiness"] = monitor.snapshot() if monitor is not None else None
    return result
