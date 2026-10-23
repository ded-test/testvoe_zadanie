import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ledger import add_entry, count_active_tasks, ensure_user, get_balance, lock_user
from app.models import Model, Task
from app.schemas import GenerateRequest, GenerateResponse
from app.services import dispatch, legs as legs_service

router = APIRouter(tags=["generate"])


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GenerateResponse,
)
async def generate(payload: GenerateRequest, session: AsyncSession = Depends(get_session)):
    task_id = uuid.uuid4()
    ref_count = len(payload.ref_images)

    # Все что касается денег и лимитов в одной транзакции
    async with session.begin():
        await ensure_user(session, payload.user_id)
        await lock_user(session, payload.user_id)

        model = await session.get(Model, payload.model_slug)
        if model is None:
            raise HTTPException(status_code=404, detail=f"unknown model {payload.model_slug!r}")

        # Проверяем есть ли хоть одна подходящая нога до списания денег
        chain = await legs_service.legs_for_model(session, model.slug)
        candidates = [leg for leg in chain if legs_service.accepts_refs(leg, ref_count)]
        if not candidates:
            raise HTTPException(
                status_code=400,
                detail=f"no leg of {model.slug} accepts {ref_count} reference images",
            )

        balance = await get_balance(session, payload.user_id)
        if balance < model.price_tokens:
            raise HTTPException(
                status_code=402,
                detail=f"insufficient tokens: balance={balance}, price={model.price_tokens}",
            )

        active = await count_active_tasks(session, payload.user_id)
        if active >= 3:  # MAX_ACTIVE_TASKS из настроек можно вынести но 3 по ТЗ
            raise HTTPException(
                status_code=429,
                detail=f"too many active tasks: {active} (max 3)",
            )

        task = Task(
            id=task_id,
            user_id=payload.user_id,
            model_slug=model.slug,
            prompt=payload.prompt,
            ref_images=payload.ref_images,
            price_tokens=model.price_tokens,
            status="queued",
        )
        session.add(task)
        await session.flush()

        # Списание idempotency_key=f'charge:{task_id}' защищает от двойного спис
        await add_entry(
            session,
            user_id=payload.user_id,
            amount=-model.price_tokens,
            kind="charge",
            idempotency_key=f"charge:{task_id}",
            task_id=task_id,
        )

        # Первая подходящая нога
        await _open_first_attempt(session, task, candidates[0])

    await dispatch.kick(task_id)

    return GenerateResponse(task_id=task_id, status="queued")


async def _open_first_attempt(session, task: Task, leg):
    from app.services.advance import _open_attempt

    await _open_attempt(session, task, leg)
