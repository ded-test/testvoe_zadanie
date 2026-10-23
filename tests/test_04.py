"""Тест 4: поздний completed после срабатывания сторожа.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from app.services import watchdog
from tests.conftest import (
    assert_ledger_matches_balance,
    get_balance,
    get_task,
    post_signed,
    provider_webhook,
)

REF_IMAGES = [f"https://example.com/{i}.png" for i in range(5)]


async def _force_deadline_past(task_id: str) -> None:
    """Не ждём 60 секунд а сдвигаем deadline в прошлое напрямую в базе"""
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text(
                "UPDATE task_attempts SET deadline_at = now() - interval '1 second' "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        )


async def test_late_completed_after_watchdog(client, user_id):
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-late",
            "user_id": str(user_id),
            "tokens": 100,
            "status": "paid",
        },
    )

    started = await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model_slug": "image-fast",
            "prompt": "a very late image",
            "ref_images": REF_IMAGES,
        },
    )
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]

    in_flight = await get_task(client, task_id)
    # только beta принимает 5 референсов цепочка из одной ноги
    assert [a["provider"] for a in in_flight["attempts"]] == ["beta"]
    external_id = in_flight["attempts"][0]["external_id"]

    # провайдер молчит и сторож сдается
    await _force_deadline_past(task_id)
    assert await watchdog.sweep_once() == 1

    timed_out = await get_task(client, task_id)
    assert timed_out["status"] == "failed"
    assert timed_out["error_type"] == "timeout"
    assert timed_out["result_url"] is None
    assert timed_out["attempts"][0]["status"] == "failed"
    assert timed_out["attempts"][0]["error_type"] == "timeout"

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 100  # полностью возвращено
    assert len([e for e in balance["entries"] if e["kind"] == "refund"]) == 1

    # приходит поздний completed 10 копий сразу
    responses = await asyncio.gather(
        *[
            provider_webhook(
                client,
                "beta",
                external_id,
                status="completed",
                error_type=None,
                result_url="https://cdn.example/beta/late.png",
            )
            for _ in range(10)
        ]
    )
    assert [r.status_code for r in responses] == [202] * 10

    final = await get_task(client, task_id)
    assert final["status"] == "failed"
    assert final["result_url"] is None

    final_balance = await get_balance(client, user_id)
    assert final_balance["balance"] == 100
    assert len([e for e in final_balance["entries"] if e["kind"] == "refund"]) == 1
    assert_ledger_matches_balance(final_balance)
