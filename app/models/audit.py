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
    TimestampMixin,
    UUIDPKMixin,
)


class AuditLog(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Tamper-evident record of mutating actions. Write at every state change.

    `tenant_id` is the tenant whose data was affected (the *acting* tenant).
    `acting_from_tenant_id` is set when a parent-tenant user is acting as a
    child via `X-Acting-Tenant-Slug` — it carries the user's home tenant so
    queries can reconstruct "who in the parent did this in the child".

    **`tenant_id` is NULLABLE here, unlike every other tenant-scoped table.**
    Some product-scoped actions genuinely have no tenant to attribute to, and
    the most important of them is a prospect invite: the invitee gets their own
    tenant when they accept, so at mint time there is nothing to point at. With
    a NOT NULL column those actions could not be recorded at all, and
    `audit.record` skipped them — which left *the single action that onboards a
    new customer* unaudited, in the system that owns identity. An audit table
    that silently drops the events it cannot scope is worse than one that
    admits a null: the gap is invisible.

    A null tenant therefore means "product-scoped, no tenant" — never "unknown".
    `product_id` stays NOT NULL, so every row is still attributable to one
    product, and tenant-scoped audit queries (`GET /api/v1/audit`) filter on an
    equality and so naturally exclude these rows rather than leaking them into
    a tenant's log.
    """

    __tablename__ = "audit_log"

    # Declared here rather than taken from `TenantScopedMixin`, which types
    # the column as NOT NULL `UUID`. Narrowing a mixin's column to
    # `UUID | None` in a subclass is a type error and, more to the point, a
    # lie about the mixin's contract: a table that may have no tenant is not
    # tenant-scoped in the sense the mixin means (its rows are never fetched
    # through `TenantRepository`'s dual filter — `GET /api/v1/audit` builds
    # explicit filters). Same FK and index as the mixin would have produced,
    # minus the NOT NULL. See the class docstring for why.
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
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
