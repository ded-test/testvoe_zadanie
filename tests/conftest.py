import json
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.security import sign

PROVIDER_NAMES = ("alpha", "beta")


async def configure_provider(name: str, patch: dict) -> None:
    """Переключить режим фейкового провайдера без перезапуска"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{settings.provider_url(name)}/_config", json=patch
        )
    response.raise_for_status()


async def post_signed(client: httpx.AsyncClient, path: str, payload: dict, *, secret: str | None = None) -> httpx.Response:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "X-Signature": sign(body, secret),
        "Content-Type": "application/json",
    }
    return await client.post(path, content=body, headers=headers)


async def provider_webhook(
    client: httpx.AsyncClient,
    provider: str,
    external_id: str,
    *,
    status: str = "failed",
    error_type: str | None = "technical",
    result_url: str | None = None,
) -> httpx.Response:
    return await post_signed(
        client,
        f"/webhooks/providers/{provider}",
        {
            "external_id": external_id,
            "status": status,
            "error_type": error_type,
            "result_url": result_url,
        },
    )


async def get_task(client: httpx.AsyncClient, task_id: str) -> dict:
    response = await client.get(f"/tasks/{task_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def get_balance(client: httpx.AsyncClient, user_id: uuid.UUID) -> dict:
    response = await client.get(f"/users/{user_id}/balance", params={"limit": 100})
    assert response.status_code == 200, response.text
    return response.json()


def assert_ledger_matches_balance(balance: dict) -> None:
    """Правило 8: баланс всегда равен сумме строк журнала."""
    assert balance["balance"] == sum(e["amount"] for e in balance["entries"])


# ---------------------------------------------------------------------------
# фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def clean_db():
    """Каждый тест начинается с пустой базы, но каталог моделей остаётся.

    Используем DELETE вместо TRUNCATE, потому что TRUNCATE требует
    исключительную блокировку всей таблицы и может зависнуть при
    параллельном запуске тестов.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM task_attempts"))
            await conn.execute(text("DELETE FROM tasks"))
            await conn.execute(text("DELETE FROM ledger_entries"))
            await conn.execute(text("DELETE FROM payments"))
            await conn.execute(text("DELETE FROM users"))
    except RuntimeError:
        pass
    yield


@pytest.fixture(autouse=True)
async def quiet_providers():
    """По умолчанию провайдеры принимают все и не присылают вебхуки"""
    for name in PROVIDER_NAMES:
        try:
            await configure_provider(
                name,
                {
                    "fail_rate": 0.0,
                    "sync_mode": "none",
                    "drop_webhook": True,
                    "duplicate_webhook": False,
                },
            )
        except httpx.HTTPError as exc:  # pragma: no cover
            pytest.skip(f"fake provider {name} is not reachable: {exc}")
    yield


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=settings.service_base_url) as http:
        yield http


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()
