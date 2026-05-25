from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    ProductScopedMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)


class AuditLog(UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base):
    """Tamper-evident record of mutating actions. Write at every state change.

    `tenant_id` is the tenant whose data was affected (the *acting* tenant).
    `acting_from_tenant_id` is set when a parent-tenant user is acting as a
    child via `X-Acting-Tenant-Slug` — it carries the user's home tenant so
    queries can reconstruct "who in the parent did this in the child".
    """

    __tablename__ = "audit_log"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acting_from_tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
