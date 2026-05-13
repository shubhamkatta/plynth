from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.subscription import SubscriptionStatus
from app.schemas.common import TimestampedResponse


class PurchaseRequest(BaseModel):
    plan_code: str
    payment_method_token: str | None = None  # provider-specific (e.g. Stripe pm_…)


class ChangePlanRequest(BaseModel):
    plan_code: str
    proration: bool = True


class CancelRequest(BaseModel):
    at_period_end: bool = True
    reason: str | None = Field(default=None, max_length=255)


class SubscriptionResponse(TimestampedResponse):
    tenant_id: UUID
    plan_id: UUID
    plan_code: str
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    trial_end: datetime | None
    grace_ends_at: datetime | None
    cancel_at_period_end: bool
    cancelled_at: datetime | None
    has_access: bool
