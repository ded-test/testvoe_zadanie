import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Task, TaskAttempt
from app.schemas import AttemptOut, TaskOut

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    rows = await session.scalars(
        select(TaskAttempt).where(TaskAttempt.task_id == task_id).order_by(TaskAttempt.leg_priority)
    )
    attempts = list(rows)
    current = next((a for a in attempts if a.status == "running"), None)

    return TaskOut(
        task_id=task.id,
        status=task.status,
        model_slug=task.model_slug,
        price_tokens=task.price_tokens,
        error_type=task.error_type,
        result_url=task.result_url,
        current_provider=current.provider if current is not None else None,
        attempts=[
            AttemptOut(
                attempt_id=a.id,
                provider=a.provider,
                leg_priority=a.leg_priority,
                status=a.status,
                external_id=a.external_id,
                error_type=a.error_type,
                result_url=a.result_url,
                started_at=a.created_at,
                finished_at=a.finished_at,
            )
            for a in attempts
        ],
    )
