from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    ProductScopedMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)


class IdempotencyKey(UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base):
    """Records the response of the first request bearing a given key, so
    retries return the same answer. Scoped per tenant + route."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", "route", name="uq_idempotency_unique"),
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
