import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request

from whisp.config import get_settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    client = httpx.AsyncClient(timeout=30)
    app.state.settings = settings
    app.state.store = None
    task = None
    try:
        pipeline = build_pipeline(settings, client)
        app.state.pipeline = pipeline
        app.state.store = pipeline.store
        if settings.poller_enabled:
            task = asyncio.create_task(_poll_forever(app))
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await client.aclose()


app = FastAPI(title="Whisp", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def health(request: Request) -> dict[str, object]:
    return {"ok": True, "poller_enabled": request.app.state.settings.poller_enabled}


@app.get("/status")
async def status(request: Request) -> dict[str, object]:
    if request.app.state.store is None:
        raise HTTPException(503, "Whisp is not configured")
    return request.app.state.store.status()

