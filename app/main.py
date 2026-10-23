import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app.api import generate, tasks, users, webhooks
from app.config import settings
from app.db import engine
from app.services import watchdog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    watchdog_task = None
    if settings.watchdog_enabled:
        watchdog_task = asyncio.create_task(watchdog.run_forever(), name="watchdog")
    try:
        yield
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog_task
        await engine.dispose()


app = FastAPI(title="Generation service", version="0.1.0", lifespan=lifespan)

app.include_router(generate.router)
app.include_router(webhooks.router)
app.include_router(tasks.router)
app.include_router(users.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
