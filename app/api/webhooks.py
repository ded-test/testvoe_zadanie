import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ledger import add_entry, ensure_user
from app.models import Payment, TaskAttempt
from app.schemas import PaymentEvent, ProviderEvent
from app.security import verify
from app.services import advance

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

BAD_SIGNATURE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="bad signature"
)

@router.post("/payments", status_code=status.HTTP_202_ACCEPTED)
async def payments_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    raw = await request.body()
    if not verify(raw, request.headers.get("X-Signature")):
        raise BAD_SIGNATURE

    try:
        event = PaymentEvent.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if event.status != "paid":
        return {"ok": True, "ignored": event.status}

    async with session.begin():
        await ensure_user(session, event.user_id)

        # payment_id первичный ключ и повторная вставка конфликт
        inserted = await session.execute(
            pg_insert(Payment)
            .values(
                payment_id=event.payment_id,
                user_id=event.user_id,
                tokens=event.tokens,
                status=event.status,
                payload=json.loads(raw),
            )
            .on_conflict_do_nothing(index_elements=["payment_id"])
            .returning(Payment.payment_id)
        )
        if inserted.scalar_one_or_none() is None:
            return {"ok": True, "duplicate": True}

        # idempotency_key=f'payment:<id>' вторая защита
        await add_entry(
            session,
            user_id=event.user_id,
            amount=event.tokens,
            kind="topup",
            idempotency_key=f"payment:{event.payment_id}",
            payment_id=event.payment_id,
        )

    return {"ok": True, "credited": event.tokens}


@router.post("/providers/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def provider_webhook(
    provider: str, request: Request, session: AsyncSession = Depends(get_session)
):
    raw = await request.body()
    if not verify(raw, request.headers.get("X-Signature")):
        raise BAD_SIGNATURE

    try:
        event = ProviderEvent.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    attempt = await session.scalar(
        select(TaskAttempt).where(
            TaskAttempt.provider == provider,
            TaskAttempt.external_id == event.external_id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="unknown external_id")

    if event.status == "completed":
        ok = await advance.complete_task_from_webhook(
            task_id=attempt.task_id,
            attempt_id=attempt.id,
            result_url=event.result_url or "",
        )
        if not ok:
            # Задача уже терминальная и (сторож вернул деньги) поздний completed игнорируем
            return {"ok": True, "ignored": "task already terminal"}
        return {"ok": True, "task_id": str(attempt.task_id)}

    # failed единая дырка отказов
    await advance.handle_failure(
        task_id=attempt.task_id,
        attempt_id=attempt.id,
        error_type=event.error_type or "technical",
        detail=f"provider {provider} reported {event.error_type}",
    )
    return {"ok": True}
