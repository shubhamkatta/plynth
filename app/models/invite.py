"""Invite tokens.

Two kinds:
- ``join_tenant`` — an existing tenant admin invites a teammate into THEIR
  tenant (``tenant_id`` set).
- ``new_tenant`` — a platform admin invites a prospect who gets their OWN
  private tenant-of-1 on accept (``tenant_id`` NULL). This is the
  therapist-onboarding path.

Only the SHA-256 of the token is stored; the raw value exists in the email
link and the create response (non-production only). Single use.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProductScopedMixin, TimestampMixin, UUIDPKMixin

INVITE_KIND_JOIN_TENANT = "join_tenant"
INVITE_KIND_NEW_TENANT = "new_tenant"


class InviteToken(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    __tablename__ = "invite_tokens"
    __table_args__ = (
        Index("uq_invite_tokens_token_hash", "token_hash", unique=True),
        Index("ix_invite_tokens_email", "email"),
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_codes: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    # Plan the prospect was pitched; echoed to the accept page so the app can
    # route straight to checkout. Informational — checkout still validates.
    plan_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
