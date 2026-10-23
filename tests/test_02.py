"""Тест 2: 10 одновременных failed на последней ноге дают один возврат

Процесс: 
пополняем баланс 
создаём задачу
первая нога отваливается вебхуком 
сервис сам переходит на вторую 
бомбим вторую ногу 10 одновременными failed 
задача failed, возврат ровно один
"""

from __future__ import annotations

import asyncio

from tests.conftest import (
    assert_ledger_matches_balance,
    get_balance,
    get_task,
    post_signed,
    provider_webhook,
)


async def test_ten_concurrent_failures_on_last_leg_refund_once(client, user_id):
    # пополняем баланс
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-refund-test",
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
            "prompt": "a cat",
            "ref_images": [],
        },
    )
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]

    # первая попытка — alpha
    after_generate = await get_task(client, task_id)
    assert [a["provider"] for a in after_generate["attempts"]] == ["alpha"]
    assert after_generate["current_provider"] == "alpha"

    # первая нога отваливается → сервис сам переходит на beta
    first_failure = await provider_webhook(
        client, "alpha", after_generate["attempts"][0]["external_id"]
    )
    assert first_failure.status_code == 202

    on_last_leg = await get_task(client, task_id)
    assert [a["provider"] for a in on_last_leg["attempts"]] == ["alpha", "beta"]
    assert on_last_leg["status"] == "running"
    assert on_last_leg["current_provider"] == "beta"

    # вторая нога (последняя) получает 10 failed одновременно
    external_id = on_last_leg["attempts"][1]["external_id"]
    responses = await asyncio.gather(
        *[
            provider_webhook(client, "beta", external_id, status="failed", error_type="technical")
            for _ in range(10)
        ]
    )
    assert all(r.status_code == 202 for r in responses)

    final = await get_task(client, task_id)
    assert final["status"] == "failed"
    assert final["current_provider"] is None
    assert [(a["provider"], a["status"]) for a in final["attempts"]] == [
        ("alpha", "failed"),
        ("beta", "failed"),
    ]

    balance = await get_balance(client, user_id)
    refunds = [e for e in balance["entries"] if e["kind"] == "refund"]
    assert len(refunds) == 1, balance
    assert refunds[0]["amount"] == 2
    # 100 начислено - 2 списано + 2 возвращено = 100
    assert balance["balance"] == 100
    assert_ledger_matches_balance(balance)

    # повторный failed не меняет ничего
    late = await provider_webhook(client, "beta", external_id, status="failed")
    assert late.status_code == 202
    balance_after = await get_balance(client, user_id)
    assert balance_after["balance"] == 100
    assert len([e for e in balance_after["entries"] if e["kind"] == "refund"]) == 1
