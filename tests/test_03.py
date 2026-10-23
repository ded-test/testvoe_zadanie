"""Тест 3: отказ первой ноги - задача завершается на второй а в истории две попытки

Также проверяем на нет подходящей ноги, не хватает токенов, больше 3 активных, и отказ без повторов
"""
from tests.conftest import (
    assert_ledger_matches_balance,
    configure_provider,
    get_balance,
    get_task,
    post_signed,
    provider_webhook,
)


async def test_first_leg_sync_failure_moves_to_second(client, user_id):
    await configure_provider("alpha", {"sync_mode": "503"})

    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-fallback",
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
            "prompt": "a dog",
            "ref_images": ["https://example.com/1.png"],
        },
    )
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]

    task = await get_task(client, task_id)
    assert task["status"] == "running"
    assert task["current_provider"] == "beta"

    attempts = task["attempts"]
    assert len(attempts) == 2, attempts
    first, second = attempts
    assert (first["provider"], first["leg_priority"], first["status"], first["error_type"]) == (
        "alpha", 1, "failed", "technical",
    )
    assert first["finished_at"] is not None
    assert (
        second["provider"],
        second["leg_priority"],
        second["status"],
        second["error_type"],
    ) == ("beta", 2, "running", None)

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 98
    kinds = [e["kind"] for e in balance["entries"]]
    assert "topup" in kinds and "charge" in kinds
    assert_ledger_matches_balance(balance)


async def test_payload_error_stops_immediately(client, user_id):
    """payload задача падает сразу.  следующая нога не пробуется"""
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-payload",
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
            "prompt": "a bird",
            "ref_images": [],
        },
    )
    task_id = started.json()["task_id"]

    first = await get_task(client, task_id)
    response = await provider_webhook(
        client, "alpha", first["attempts"][0]["external_id"],
        status="failed", error_type="payload",
    )
    assert response.status_code == 202

    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert task["error_type"] == "payload"
    assert len(task["attempts"]) == 1  # beta не пробовалась

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 100
    assert len([e for e in balance["entries"] if e["kind"] == "refund"]) == 1


async def test_no_leg_accepts_refs_is_400_and_costs_nothing(client, user_id):
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-refs",
            "user_id": str(user_id),
            "tokens": 100,
            "status": "paid",
        },
    )

    response = await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model_slug": "image-fast",
            "prompt": "too many refs",
            "ref_images": [f"https://example.com/{i}.png" for i in range(11)],
        },
    )
    assert response.status_code == 400

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 100
    assert [e["kind"] for e in balance["entries"]] == ["topup"]


async def test_not_enough_tokens_is_402(client, user_id):
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-broke",
            "user_id": str(user_id),
            "tokens": 1,
            "status": "paid",
        },
    )

    response = await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model_slug": "image-fast",
            "prompt": "x",
            "ref_images": [],
        },
    )
    assert response.status_code == 402

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 1
    assert [e["kind"] for e in balance["entries"]] == ["topup"]


async def test_fourth_active_task_is_429(client, user_id):
    await post_signed(
        client,
        "/webhooks/payments",
        {
            "payment_id": "pay-limit",
            "user_id": str(user_id),
            "tokens": 100,
            "status": "paid",
        },
    )

    for _ in range(3):
        response = await client.post(
            "/generate",
            json={
                "user_id": str(user_id),
                "model_slug": "image-fast",
                "prompt": "x",
                "ref_images": [],
            },
        )
        assert response.status_code == 202, response.text

    response = await client.post(
        "/generate",
        json={
            "user_id": str(user_id),
            "model_slug": "image-fast",
            "prompt": "x",
            "ref_images": [],
        },
    )
    assert response.status_code == 429

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 94  # три списания по 2
    assert len([e for e in balance["entries"] if e["kind"] == "charge"]) == 3
