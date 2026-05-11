from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProductScopedMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.permission import RolePermission
    from app.models.user import User


class Role(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Role definition. Roles are per-product.

    `tenant_id` is nullable: NULL means a *system* role available to every
    tenant in the product (owner / admin / member). Tenant-scoped roles let
    a tenant define its own custom roles without polluting global state.
    """

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("product_id", "tenant_id", "name", name="uq_roles_product_tenant_name"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    bindings: Mapped[list["UserRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class UserRole(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Binds a User to a Role, optionally scoped to a specific (child) tenant.

    Same user can hold different roles in parent vs child tenants.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope_tenant_id", name="uq_user_roles_unique"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="role_bindings")
    role: Mapped["Role"] = relationship(back_populates="bindings")
