import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from whisp import __version__
from whisp.config import Settings, get_settings
from whisp.core.errors import safe_error_message
from whisp.core.pipeline import Pipeline
from whisp.core.readiness import ReadinessMonitor
from whisp.dashboard import router as dashboard_router
from whisp.landing import router as landing_router
from whisp.logging_config import configure_logging
from whisp.outputs.telegram import TelegramOutput
from whisp.runtime import build_runtime
from whisp.webhooks.telegram import router as telegram_router

logger = logging.getLogger(__name__)

DIGEST_CHECK_SECONDS = 60


async def _every(seconds: int, job: Callable[[], Awaitable[None]], name: str) -> None:
    """Run a background job forever; a failure is logged and retried on the next tick."""
    while True:
        try:
            await job()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "%s failed; retrying on the next interval: %s", name, safe_error_message(exc)
            )
        await asyncio.sleep(seconds)


async def _poll(pipeline: Pipeline) -> None:
    result = await pipeline.run_once()
    logger.info("Poll complete: %s", result)


async def _send_digest_if_due(pipeline: Pipeline, settings: Settings) -> None:
    sent = await pipeline.send_digest_if_due(datetime.now(settings.zone), settings.digest_time)
    if sent is not None:
        logger.info("Digest sent with %d messages", sent)


async def _register_webhook(telegram: TelegramOutput, settings: Settings) -> None:
    assert settings.public_base_url
    assert settings.telegram_webhook_secret
    url = f"{settings.public_base_url}/telegram/webhook"
    try:
        await telegram.set_webhook(url, settings.telegram_webhook_secret.get_secret_value())
        logger.info("Telegram webhook registered at %s", url)
    except Exception as exc:
        # Not fatal: notifications keep working, and the next restart retries.
        logger.error("Telegram webhook registration failed: %s", safe_error_message(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    async with httpx.AsyncClient(timeout=30) as client:
        runtime = build_runtime(settings, client)
        pipeline = runtime.pipeline
        readiness = ReadinessMonitor(pipeline)
        state = app.state
        state.settings = settings
        state.store = runtime.store
        state.pipeline = pipeline
        state.readiness = readiness
        state.telegram = runtime.telegram
        state.chat_agent = runtime.chat_agent if settings.chat_enabled else None
        state.chat_tasks = set()
        state.chat_lock = asyncio.Lock()

        jobs = [
            _every(settings.readiness_check_interval_seconds, readiness.refresh, "Readiness check")
        ]
        if settings.poller_enabled:
            jobs.append(_every(settings.poll_interval_seconds, lambda: _poll(pipeline), "Poll"))
        if settings.digest_enabled:
            jobs.append(
                _every(
                    DIGEST_CHECK_SECONDS,
                    lambda: _send_digest_if_due(pipeline, settings),
                    "Digest",
                )
            )
        tasks = [asyncio.create_task(job) for job in jobs]
        if settings.webhook_configured:
            await _register_webhook(runtime.telegram, settings)
        try:
            yield
        finally:
            for task in [*tasks, *state.chat_tasks]:
                task.cancel()
            for task in [*tasks, *state.chat_tasks]:
                with contextlib.suppress(asyncio.CancelledError):
                    await task


app = FastAPI(title="Whisp", version=__version__, lifespan=lifespan)
app.include_router(landing_router)
app.include_router(dashboard_router)
app.include_router(telegram_router)


@app.get("/healthz")
async def health(request: Request) -> dict[str, object]:
    return {"ok": True, "poller_enabled": request.app.state.settings.poller_enabled}


@app.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    snapshot = request.app.state.readiness.snapshot()
    return JSONResponse(status_code=200 if snapshot["ready"] else 503, content=snapshot)


@app.get("/status")
async def status(request: Request) -> dict[str, object]:
    state = request.app.state
    return {
        **state.store.status(),
        "git_commit": state.settings.git_commit,
        "readiness": state.readiness.snapshot(),
    }
