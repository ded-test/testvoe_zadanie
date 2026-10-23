import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.ledger import add_entry
from app.models import Leg, Task, TaskAttempt
from app.services import legs as legs_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _open_attempt(session: AsyncSession, task: Task, leg: Leg):
    """Создать попытку для ноги и сделать ее текущей у задачи"""
    attempt = TaskAttempt(
        id=uuid.uuid4(),
        task_id=task.id,
        leg_priority=leg.priority,
        provider=leg.provider,
        status="running",
        deadline_at=_now() + timedelta(seconds=settings.provider_timeout_seconds),
    )
    session.add(attempt)
    task.status = "running"
    await session.flush()
    return attempt


async def _claim_attempt_failed(
    session: AsyncSession, attempt_id: uuid.UUID, *, error_type: str, detail: str | None = None
):
    """Пометить попытку неудавшейся вернуть None если уже обработана другим.

    UPDATE WHERE status='running' атомарен поэтому из 10 одновременых вебхуков только один пройдет
    """
    row = await session.execute(
        update(TaskAttempt)
        .where(TaskAttempt.id == attempt_id, TaskAttempt.status == "running")
        .values(
            status="failed",
            error_type=error_type,
            error_detail=detail,
            finished_at=_now(),
        )
        .returning(TaskAttempt)
    )
    return row.scalar_one_or_none()


async def _fail_task(session: AsyncSession, task: Task, *, error_type: str):
    """Завершить задачу как неудачную и вернуть деньги ровно один раз

    idempotency_key='refund:<task_id>' защищает от двойного возврата и даже если функция вызовется дважды
    """
    task.status = "failed"
    task.error_type = error_type
    task.finished_at = _now()
    await add_entry(
        session,
        user_id=task.user_id,
        amount=task.price_tokens,
        kind="refund",
        idempotency_key=f"refund:{task.id}",
        task_id=task.id,
    )


async def _complete_task(session: AsyncSession, task: Task, *, result_url: str):
    """Завершить задачу"""
    task.status = "completed"
    task.result_url = result_url
    task.finished_at = _now()


async def handle_failure(
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    error_type: str,
    detail: str | None = None,
) -> None:
    """Основная воронк отказов вызывается из вебхука + диспетчера и сторожа."""
    async with SessionLocal() as session, session.begin():
        # Берем задачу на запись - чтоб параллельные вебхуки не мешали друг другу
        result = await session.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        task = result.scalar_one_or_none()
        if task is None or task.status in ("completed", "failed"):
            return

        attempt = await _claim_attempt_failed(
            session, attempt_id, error_type=error_type, detail=detail
        )
        if attempt is None:
            return

        if error_type == "payload":
            # запрос неверной формы
            await _fail_task(session, task, error_type="payload")
            return

        # ищем некст ногу
        skip = error_type == "moderation"
        next_leg = await legs_service.next_leg(
            session,
            task.model_slug,
            len(task.ref_images),
            after_priority=attempt.leg_priority,
            skip_on_moderation=skip,
        )

        if next_leg is None:
            await _fail_task(session, task, error_type=error_type)
        else:
            await _open_attempt(session, task, next_leg)

    if next_leg is not None:
        from app.services import dispatch

        await dispatch.kick(task_id)


async def complete_task_from_webhook(
    task_id: uuid.UUID, attempt_id: uuid.UUID, result_url: str
) -> bool:
    """Пометить попытку успешной и задачу завершенонй

    Возвращает False если задача уже терминальная поздний типо completed после сторожа
    """
    async with SessionLocal() as session, session.begin():
        result = await session.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        task = result.scalar_one_or_none()
        if task is None or task.status in ("completed", "failed"):
            return False

        attempt = await session.execute(
            update(TaskAttempt)
            .where(TaskAttempt.id == attempt_id, TaskAttempt.status == "running")
            .values(status="completed", result_url=result_url, finished_at=_now())
            .returning(TaskAttempt)
        )
        if attempt.scalar_one_or_none() is None:
            return False

        await _complete_task(session, task, result_url=result_url)
    return True
