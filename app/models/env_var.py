"""Per-product environment variable (secrets vault).

Each row is one (product_id, key) → encrypted value pair. ``is_secret``
controls whether the value is stored encrypted (true; default) or in
plaintext (false; for public config like display URLs). Encryption is
AES-256-GCM with AAD = ``product_id||key``; see ``app.core.crypto``.

Lifecycle:
- Created/updated through ``app.services.env_var.set_var``.
- Read by product backends via the ``GET /api/v1/env`` endpoint
  authenticated with a ``ProductServiceToken``.
- Admin reveals through ``GET /admin/products/{slug}/env/{key}?reveal=true``
  require a ``reason`` query param and write a high-severity audit row.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    ProductScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
    utcnow,
)


class ProductEnvVar(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    __tablename__ = "product_env_vars"
    __table_args__ = (
        Index(
            "uq_product_env_vars_key",
            "product_id", "key",
            unique=True,
        ),
    )

    # Conventional env-var name: `^[A-Z][A-Z0-9_]{0,127}$`. Length cap
    # of 128 matches the schema validator.
    key: Mapped[str] = mapped_column(String(128), nullable=False)

    # Encrypted blob: nonce(12) || ciphertext+tag. For is_secret=false
    # values we still store the plaintext as bytes (utf-8 encoded) so
    # the column type is uniform — the encryption layer is bypassed.
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # True (default) => encrypted at rest, masked in list responses,
    # admin reveal requires `?reveal=true&reason=...`.
    # False           => stored as utf-8 plaintext, returned in plain
    #                    listings. Use for public-safe config.
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stamped on set/update for rotation visibility. Distinct from
    # `updated_at` (which moves on any row touch including metadata edits).
    # TIMESTAMPTZ to match the migration and avoid asyncpg's
    # "can't subtract offset-naive and offset-aware" rejection.
    last_rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
