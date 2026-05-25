from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    ProductScopedMixin,
    SoftDeleteMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)

if TYPE_CHECKING:
    from app.models.role import UserRole
    from app.models.tenant import Tenant


class User(
    UUIDPKMixin, TimestampMixin, SoftDeleteMixin, ProductScopedMixin, TenantScopedMixin, Base
):
    __tablename__ = "users"
    __table_args__ = (
        # Email is unique per tenant — but only among non-deleted rows, so
        # admin can re-invite an email after soft-delete. Existing dbs are
        # migrated by scripts/migrate.py (0002).
        Index(
            "uq_users_tenant_email_alive",
            "tenant_id", "email",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    role_bindings: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Server-side refresh-token registry — enables revocation on logout /
    password change. `jti` is the JWT identifier; we store a hash only."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_refresh_tokens_jti"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PasswordResetToken(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Single-use forgot-password token. We store only the SHA-256 of the
    secret so a DB leak doesn't hand attackers a working reset link.
    Tokens are short-lived (default 1 hour); confirming consumes the row."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
