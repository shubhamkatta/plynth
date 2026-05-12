"""Credit accounting.

Two tables:
- `credit_wallets` — current balance per (tenant, feature_key). Single row,
  updated atomically via SELECT FOR UPDATE during consumption.
- `credit_ledger` — append-only journal of every grant / debit / expiry /
  refund. The wallet balance is the sum of its ledger entries; the wallet is
  cached for fast reads but always reconcilable.

Always write to the ledger first inside the same transaction that updates the
wallet. See `app/services/credit.py`.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    ProductScopedMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)


class CreditEntryType(str, enum.Enum):
    GRANT = "grant"          # issued by plan / manual top-up
    DEBIT = "debit"          # consumed by user action
    REFUND = "refund"        # reverses a debit
    EXPIRY = "expiry"        # period reset; positive grants expiring
    ADJUSTMENT = "adjustment"  # admin


class CreditWallet(UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base):
    __tablename__ = "credit_wallets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "feature_key", name="uq_credit_wallets_unique"),
    )

    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditLedger(UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base):
    __tablename__ = "credit_ledger"

    wallet_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("credit_wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[CreditEntryType] = mapped_column(
        Enum(CreditEntryType, name="credit_entry_type"), nullable=False
    )
    # Signed amount: positive credits the wallet, negative debits it.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # External reference (e.g. invoice id, request id) to dedupe replays.
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
