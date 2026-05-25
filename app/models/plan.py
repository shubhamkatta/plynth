from __future__ import annotations

import enum
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, ProductScopedMixin, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.subscription import Subscription


class BillingInterval(str, enum.Enum):
    MONTH = "month"
    YEAR = "year"
    ONE_TIME = "one_time"


class Plan(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """Plan catalog entry, per-product. Public plans show in /plans;
    non-public are for enterprise/custom deals."""

    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("product_id", "code", name="uq_plans_product_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, name="billing_interval"),
        default=BillingInterval.MONTH,
        nullable=False,
    )
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Provider IDs (Stripe price ID, etc) — keyed by provider name.
    provider_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    features: Mapped[list[PlanFeature]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan")


class PlanFeature(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """A per-plan feature limit or credit allotment.

    - `feature_key` is your app's identifier (e.g. `api.calls`, `seats`,
      `storage.gb`, `credits.ai_completion`).
    - `limit_value` NULL means unlimited.
    - `credit_amount` — if set, this many credits are issued at every billing
      cycle start (see app/services/credit.py).
    """

    __tablename__ = "plan_features"
    __table_args__ = (
        UniqueConstraint("plan_id", "feature_key", name="uq_plan_features_unique"),
    )

    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    is_hard_limit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    plan: Mapped[Plan] = relationship(back_populates="features")
