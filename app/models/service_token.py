"""Per-product service tokens.

A long-lived, scoped credential issued to a product's backend so it can
authenticate to ``GET /api/v1/env`` (and future product-level endpoints)
without holding a platform-admin token or a user JWT.

Format
    ``pst_<32-hex>`` — 44 chars, shell-safe, no padding. The raw value
    is shown ONCE at creation; we store only the SHA-256 hash. A DB
    leak cannot recover the plaintext.

Scopes
    JSONB array of permission strings. v1 ships ``env:read`` only. Add
    more as new product-scoped endpoints land.

Forensics
    ``last_used_at`` and ``last_used_ip`` are updated on every successful
    authentication. Use ``GET /admin/products/{slug}/service-tokens`` to
    audit usage and rotate stale tokens.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProductScopedMixin, TimestampMixin, UUIDPKMixin


class ProductServiceToken(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    __tablename__ = "product_service_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_service_tokens_token_hash"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # SHA-256 hex of the bearer token. Never stores the plaintext.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # JSONB array of scope strings. e.g. ["env:read"]. The authorize
    # dependency checks set membership; absent scope → 403.
    scopes: Mapped[list[Any]] = mapped_column(
        JSONB, default=lambda: ["env:read"], nullable=False
    )

    expires_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_ip:  Mapped[str | None]      = mapped_column(String(64), nullable=True)

    @property
    def is_alive(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None:
            # Compared in service layer where we already have utcnow handy.
            return True
        return True
