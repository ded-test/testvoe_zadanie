import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerateRequest(BaseModel):
    user_id: uuid.UUID
    model_slug: str
    prompt: str = Field(min_length=1)
    ref_images: list[str] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    task_id: uuid.UUID
    status: str


class AttemptOut(BaseModel):
    attempt_id: uuid.UUID
    provider: str
    leg_priority: int
    status: str
    external_id: str | None = None
    error_type: str | None = None
    result_url: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskOut(BaseModel):
    task_id: uuid.UUID
    status: str
    model_slug: str
    price_tokens: int
    error_type: str | None = None
    result_url: str | None = None
    current_provider: str | None = None
    attempts: list[AttemptOut]


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    amount: int
    kind: str
    task_id: uuid.UUID | None = None
    payment_id: str | None = None
    created_at: datetime


class BalanceOut(BaseModel):
    user_id: uuid.UUID
    balance: int
    entries: list[LedgerEntryOut]


class ProviderEvent(BaseModel):
    external_id: str
    status: Literal["completed", "failed"]
    result_url: str | None = None
    error_type: Literal["technical", "moderation", "payload"] | None = None


class PaymentEvent(BaseModel):
    payment_id: str
    user_id: uuid.UUID
    tokens: int = Field(gt=0)
    status: Literal["paid", "pending", "failed"]
