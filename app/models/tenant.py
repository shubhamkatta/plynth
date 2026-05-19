"""Tenant hierarchy: top-level customer + optional child tenants (departments,
subsidiaries, workspaces). Tenants form a tree via `parent_id`.

Tenants belong to exactly one Product — same slug can repeat across products.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    ProductScopedMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPKMixin,
)

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user import User


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"      # billing-driven or admin action
    DEACTIVATED = "deactivated"  # explicit shutdown
    DELETED = "deleted"          # soft-deleted; do not allow auth


class TenantType(str, enum.Enum):
    """B2B vs B2C marker. Behavior is identical under the hood (tenant
    is the billing / audit / RBAC boundary); product UIs use this to
    render team-aware vs single-user flows."""
    COMPANY = "company"
    INDIVIDUAL = "individual"


class Tenant(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, ProductScopedMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("product_id", "slug", name="uq_tenants_product_slug"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status"),
        default=TenantStatus.ACTIVE,
        nullable=False,
    )
    type: Mapped[TenantType] = mapped_column(
        Enum(TenantType, name="tenant_type"),
        default=TenantType.COMPANY,
        nullable=False,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    is_root: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def is_individual(self) -> bool:
        return self.type == TenantType.INDIVIDUAL

    parent: Mapped["Tenant | None"] = relationship(
        "Tenant", remote_side="Tenant.id", back_populates="children"
    )
    children: Mapped[list["Tenant"]] = relationship(
        "Tenant", back_populates="parent", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="tenant", uselist=False, cascade="all, delete-orphan"
    )
