"""Фейковый провайдер alpha beta

Одна и та же программа запускается дважды с разным PROVIDER_NAME и портом

Поведение настраивается переменными окружения и endpointом POST /_config чтобы тесты могли включать отказы без перезапуска контейнера
"""
import asyncio
import hashlib
import hmac
import json
import os
import random
import uuid
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

PROVIDER_NAME = os.getenv("PROVIDER_NAME", "alpha")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "dev-shared-secret")


class Behavior(BaseModel):
    fail_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    fail_error_type: Literal["technical", "moderation", "payload"] = "technical"
    sync_mode: Literal["none", "503", "timeout"] = "none"
    sync_timeout_seconds: float = 15.0
    duplicate_webhook: bool = False
    drop_webhook: bool = False
    min_delay_ms: int = 2000
    max_delay_ms: int = 20000


app = FastAPI(title=f"fake provider {PROVIDER_NAME}")

_state = Behavior(
    fail_rate=float(os.getenv("FAIL_RATE", "0")),
    fail_error_type=os.getenv("FAIL_ERROR_TYPE", "technical"),
    sync_mode=os.getenv("SYNC_MODE", "none"),
    duplicate_webhook=os.getenv("DUPLICATE_WEBHOOK", "false").lower() == "true",
    drop_webhook=os.getenv("DROP_WEBHOOK", "false").lower() == "true",
    min_delay_ms=int(os.getenv("MIN_DELAY_MS", "2000")),
    max_delay_ms=int(os.getenv("MAX_DELAY_MS", "20000")),
)

_bg: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "provider": PROVIDER_NAME}


@app.get("/_config")
async def get_config() -> dict:
    return _state.model_dump()


@app.post("/_config")
async def set_config(patch: dict) -> dict:
    """Частичное обновление поведения, например {"sync_mode": "503"}."""
    global _state
    _state = _state.model_copy(update=patch)
    return _state.model_dump()


@app.post("/_reset")
async def reset_config() -> dict:
    global _state
    _state = Behavior()
    return _state.model_dump()


@app.post("/tasks", status_code=202)
async def create_task(payload: dict) -> dict:
    cfg = _state

    if cfg.sync_mode == "503":
        raise HTTPException(status_code=503, detail="provider is temporarily unavailable")
    if cfg.sync_mode == "timeout":
        # клиент должен получить таймаут до ответа
        await asyncio.sleep(cfg.sync_timeout_seconds)

    external_id = f"{PROVIDER_NAME}-{uuid.uuid4().hex}"
    callback_url = payload.get("callback_url")
    failed = random.random() < cfg.fail_rate
    error_type = cfg.fail_error_type if failed else None

    _spawn(
        _deliver(
            external_id=external_id,
            callback_url=callback_url,
            failed=failed,
            error_type=error_type,
            cfg=cfg,
        )
    )
    return {"external_id": external_id, "provider": PROVIDER_NAME}


async def _deliver(
    *,
    external_id: str,
    callback_url: str | None,
    failed: bool,
    error_type: str | None,
    cfg: Behavior,
) -> None:
    delay_ms = random.randint(cfg.min_delay_ms, max(cfg.min_delay_ms, cfg.max_delay_ms))
    await asyncio.sleep(delay_ms / 1000)

    if cfg.drop_webhook or not callback_url:
        return

    body_dict = {
        "external_id": external_id,
        "status": "failed" if failed else "completed",
        "result_url": None if failed else f"https://cdn.example/{PROVIDER_NAME}/{external_id}.png",
        "error_type": error_type,
    }
    body = json.dumps(body_dict, separators=(",", ":")).encode()
    headers = {"X-Signature": _sign(body), "Content-Type": "application/json"}

    async def send_once() -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(callback_url, content=body, headers=headers)
        except httpx.HTTPError:
            pass  # провайдер не ретраит - сторож на стороне сервиса страхует

    if cfg.duplicate_webhook:
        # оба вебхука одновременно
        await asyncio.gather(send_once(), send_once())
    else:
        await send_once()
