"""Тест 1: 20 одновременных одинаковых вебхуков оплаты дают одно начисление"""
import asyncio

from tests.conftest import assert_ledger_matches_balance, get_balance, post_signed


async def test_twenty_simultaneous_payment_webhooks_credit_once(client, user_id):
    payload = {
        "payment_id": "pay-simultaneous-1",
        "user_id": str(user_id),
        "tokens": 100,
        "status": "paid",
    }

    responses = await asyncio.gather(
        *[post_signed(client, "/webhooks/payments", payload) for _ in range(20)]
    )

    assert [r.status_code for r in responses] == [202] * 20
    # ровно один из них начислил деньги.  остальные дубликаты
    credited = [r.json().get("credited") for r in responses if r.json().get("credited")]
    assert len(credited) == 1

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 100
    assert len(balance["entries"]) == 1
    assert balance["entries"][0]["kind"] == "topup"
    assert balance["entries"][0]["payment_id"] == "pay-simultaneous-1"
    assert_ledger_matches_balance(balance)


async def test_retry_payment_is_no_op(client, user_id):
    payload = {
        "payment_id": "pay-retry-1",
        "user_id": str(user_id),
        "tokens": 40,
        "status": "paid",
    }
    assert (await post_signed(client, "/webhooks/payments", payload)).status_code == 202
    assert (await post_signed(client, "/webhooks/payments", payload)).status_code == 202

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 40
    assert len(balance["entries"]) == 1


async def test_bad_signature_rejected(client, user_id):
    payload = {
        "payment_id": "pay-forged-1",
        "user_id": str(user_id),
        "tokens": 1000,
        "status": "paid",
    }
    response = await post_signed(
        client, "/webhooks/payments", payload, secret="not-the-secret"
    )
    assert response.status_code == 401

    balance = await get_balance(client, user_id)
    assert balance["balance"] == 0
    assert balance["entries"] == []
