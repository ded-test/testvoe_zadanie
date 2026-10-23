import uuid

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Task, TaskAttempt
from app.services import advance

# стаусы которые считаются синхронной ошибкой
_SYNC_FAILURE_CODES = {408, 425, 429, 500, 502, 503, 504}


async def kick(task_id: uuid.UUID, *, max_steps: int = 8) -> None:
    """Попытаться отправить текущую попытку, при синхронной ошибке мы идем к следующей ноге"""
    for _ in range(max_steps):
        outcome = await _send_current_attempt(task_id)
        if outcome != "sync_failure":
            return


async def _send_current_attempt(task_id: uuid.UUID) -> str:
    """Вернуть 'sent' | 'sync_failure' | 'noop'     """
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if task is None or task.status not in ("queued", "running"):
            return "noop"

        # Находим попытку со статусом раннинг
        result = await session.execute(
            select(TaskAttempt).where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.status == "running"
            )
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            return "noop"

        provider = attempt.provider
        attempt_id = attempt.id
        payload = {
            "external_task_id": str(attempt.id),
            "model_slug": task.model_slug,
            "prompt": task.prompt,
            "ref_images": task.ref_images,
            "callback_url": f"{settings.webhook_base_url}/webhooks/providers/{provider}",
        }

    url = f"{settings.provider_url(provider)}/tasks"
    try:
        async with httpx.AsyncClient(timeout=settings.dispatch_timeout_seconds) as client:
            response = await client.post(url, json=payload)
        if response.status_code in _SYNC_FAILURE_CODES:
            raise ProviderSyncError(f"{provider} returned {response.status_code}")
        response.raise_for_status()
        external_id = response.json()["external_id"]
    except (httpx.HTTPError, ProviderSyncError, KeyError, ValueError) as exc:
        await advance.handle_failure(
            task_id=task_id,
            attempt_id=attempt_id,
            error_type="technical",
            detail=str(exc),
        )
        return "sync_failure"

    async with SessionLocal() as session:
        await session.execute(
            update(TaskAttempt)
            .where(TaskAttempt.id == attempt_id, TaskAttempt.status == "running")
            .values(external_id=external_id)
        )
        await session.commit()
    return "sent"


class ProviderSyncError(Exception):
    pass
