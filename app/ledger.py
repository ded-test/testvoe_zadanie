import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LedgerEntry, Task, User


async def ensure_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Создать пользователя если его ещё нет (регистрации нет появляется на первом контакте)"""
    stmt = pg_insert(User).values(id=user_id).on_conflict_do_nothing(index_elements=["id"])
    await session.execute(stmt)


async def lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Заблокировать строку пользователя чтобы параллельные запросы одного юзера не читали баланс дважды"""
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())


async def get_balance(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(LedgerEntry.user_id == user_id)
    )
    return int(total or 0)


async def add_entry(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: str,
    idempotency_key: str,
    task_id: uuid.UUID | None = None,
    payment_id: str | None = None,
) -> bool:
    """Добавить строку в журнал + Вернуть False, если такой ключ уже был

    UNIQUE на idempotency_key гарантирует что даже при 10 одновременных запросах деньги сдвинутся один раз
    """
    stmt = (
        pg_insert(LedgerEntry)
        .values(
            user_id=user_id,
            amount=amount,
            kind=kind,
            idempotency_key=idempotency_key,
            task_id=task_id,
            payment_id=payment_id,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(LedgerEntry.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    return inserted is not None


async def count_active_tasks(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.user_id == user_id, Task.status.in_(("queued", "running")))
    )
    return int(total or 0)


async def recent_entries(session: AsyncSession, user_id: uuid.UUID, limit: int = 20):
    rows = await session.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .order_by(LedgerEntry.id.desc())
        .limit(limit)
    )
    return list(rows)
