from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Model(Base):
    __tablename__ = "models"

    slug = Column(Text, primary_key=True)
    price_tokens = Column(Integer, nullable=False)


class Leg(Base):
    """Нога — модель + провайдер, вместе первичный ключ"""
    __tablename__ = "legs"

    model_slug = Column(Text, ForeignKey("models.slug", ondelete="CASCADE"), primary_key=True)
    provider = Column(Text, primary_key=True)
    priority = Column(Integer, nullable=False)
    max_ref_images = Column(Integer, nullable=False, default=0)
    skip_on_moderation = Column(Boolean, nullable=False, default=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    model_slug = Column(Text, ForeignKey("models.slug"), nullable=False)
    prompt = Column(Text, nullable=False)
    ref_images = Column(JSONB, nullable=False, default=list)
    price_tokens = Column(Integer, nullable=False)
    status = Column(Text, nullable=False)
    error_type = Column(Text)
    result_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))


class TaskAttempt(Base):
    """Одна попытка одной ноги. Сюда приходят вебхуки провайдера."""
    __tablename__ = "task_attempts"

    id = Column(UUID(as_uuid=True), primary_key=True)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    leg_priority = Column(Integer, nullable=False)
    provider = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    error_type = Column(Text)
    external_id = Column(Text)
    result_url = Column(Text)
    error_detail = Column(Text)
    deadline_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))


class LedgerEntry(Base):
    """Журнал операций. Баланс = сумма amount по пользователю."""
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    kind = Column(Text, nullable=False)  # topup | charge | refund
    idempotency_key = Column(Text, nullable=False, unique=True)
    task_id = Column(UUID(as_uuid=True))
    payment_id = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(Text, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tokens = Column(Integer, nullable=False)
    status = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
