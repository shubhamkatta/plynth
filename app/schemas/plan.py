from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.plan import BillingInterval
from app.schemas.common import TimestampedResponse


class PlanFeatureIn(BaseModel):
    feature_key: str = Field(min_length=1, max_length=64)
    limit_value: Decimal | None = None
    credit_amount: Decimal | None = None
    is_hard_limit: bool = True
    meta: dict[str, Any] = Field(default_factory=dict)


class PlanFeatureOut(PlanFeatureIn):
    id: UUID


class PlanCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    name: str
    description: str | None = None
    price_cents: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    interval: BillingInterval = BillingInterval.MONTH
    trial_days: int = Field(default=0, ge=0)
    is_public: bool = True
    features: list[PlanFeatureIn] = Field(default_factory=list)
    provider_refs: dict[str, Any] = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    # Reject unknown fields with 422 instead of silently dropping them.
    # Previously a PATCH like {"trial_days": 30} returned 200 OK but did
    # nothing because trial_days wasn't on the allow-list — confusing.
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    interval: BillingInterval | None = None
    trial_days: int | None = Field(default=None, ge=0)
    is_public: bool | None = None
    is_active: bool | None = None
    provider_refs: dict[str, Any] | None = None


class PlanResponse(TimestampedResponse):
    code: str
    name: str
    description: str | None
    price_cents: int
    currency: str
    interval: BillingInterval
    trial_days: int
    is_public: bool
    is_active: bool
    features: list[PlanFeatureOut]
