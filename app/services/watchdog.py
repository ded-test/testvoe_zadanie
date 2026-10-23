import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import TaskAttempt
from app.services import advance

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def sweep_once() -> int:
    """Найти просроченные попытки и отправить их через handle_failure

    Возвращает количество обработанных попыток (фор тестс).
    """
    async with SessionLocal() as session, session.begin():
        result = await session.execute(
            select(TaskAttempt.id, TaskAttempt.task_id)
            .where(TaskAttempt.status == "running")
            .where(TaskAttempt.deadline_at < _now())
            .with_for_update(skip_locked=True)
        )
        expired = list(result.all())

    handled = 0
    for attempt_id, task_id in expired:
        await advance.handle_failure(task_id, attempt_id, "timeout", "watchdog timeout")
        handled += 1
    return handled


async def run_forever() -> None:
    logger.info("watchdog started, interval=%ss", settings.watchdog_interval_seconds)
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("watchdog sweep failed")
        await asyncio.sleep(settings.watchdog_interval_seconds)
