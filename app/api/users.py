import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ledger import get_balance, recent_entries
from app.schemas import BalanceOut, LedgerEntryOut

router = APIRouter(tags=["users"])


@router.get("/users/{user_id}/balance", response_model=BalanceOut)
async def user_balance(
    user_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    balance = await get_balance(session, user_id)
    entries = await recent_entries(session, user_id, limit=limit)
    return BalanceOut(
        user_id=user_id,
        balance=balance,
        entries=[LedgerEntryOut.model_validate(e) for e in entries],
    )
