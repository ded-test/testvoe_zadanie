from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Leg


async def legs_for_model(session: AsyncSession, model_slug: str):
    rows = await session.scalars(
        select(Leg).where(Leg.model_slug == model_slug).order_by(Leg.priority)
    )
    return list(rows)


def accepts_refs(leg, ref_count: int) -> bool:
    return leg.max_ref_images >= ref_count


async def next_leg(
    session: AsyncSession,
    model_slug: str,
    ref_count: int,
    *,
    after_priority: int,
    skip_on_moderation: bool,
):
    """Следующая нога по приоритету после after_priority

    skip_on_moderation=True пропускает ноги с флагом skip_on_moderation
    """
    legs = await legs_for_model(session, model_slug)
    for leg in legs:
        if leg.priority <= after_priority:
            continue
        if not accepts_refs(leg, ref_count):
            continue
        if skip_on_moderation and leg.skip_on_moderation:
            continue
        return leg
    return None
