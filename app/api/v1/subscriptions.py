from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, get_idempotency_key, require_permission
from app.core.tenant import current_tenant_id
from app.models.subscription import Subscription
from app.schemas.subscription import (
    CancelRequest,
    ChangePlanRequest,
    PurchaseRequest,
    SubscriptionResponse,
)
from app.services import subscription as sub_svc

router = APIRouter()


def _serialise(sub: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id, created_at=sub.created_at, updated_at=sub.updated_at,
        tenant_id=sub.tenant_id, plan_id=sub.plan_id,
        plan_code=sub.plan.code if sub.plan else "",
        status=sub.status, current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end, trial_end=sub.trial_end,
        grace_ends_at=sub.grace_ends_at, cancel_at_period_end=sub.cancel_at_period_end,
        cancelled_at=sub.cancelled_at, has_access=sub.has_access,
    )


@router.get("", response_model=SubscriptionResponse,
            dependencies=[Depends(require_permission("subscriptions:read"))])
async def get_subscription(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> SubscriptionResponse:
    sub = await sub_svc.get_for_tenant(db, current_tenant_id() or user.tenant_id)
    return _serialise(sub)


@router.post("/purchase", response_model=SubscriptionResponse,
             dependencies=[Depends(require_permission("subscriptions:purchase"))])
async def purchase(
    payload: PurchaseRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
) -> SubscriptionResponse:
    sub = await sub_svc.purchase(
        db,
        tenant_id=current_tenant_id() or user.tenant_id,
        plan_code=payload.plan_code,
        payment_method_token=payload.payment_method_token,
        actor_user_id=user.id,
        idempotency_key=idempotency_key,
    )
    return _serialise(sub)


@router.post("/change", response_model=SubscriptionResponse,
             dependencies=[Depends(require_permission("subscriptions:change"))])
async def change(
    payload: ChangePlanRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
) -> SubscriptionResponse:
    sub = await sub_svc.change_plan(
        db,
        tenant_id=current_tenant_id() or user.tenant_id,
        new_plan_code=payload.plan_code,
        proration=payload.proration,
        actor_user_id=user.id,
        idempotency_key=idempotency_key,
    )
    return _serialise(sub)


@router.post("/cancel", response_model=SubscriptionResponse,
             dependencies=[Depends(require_permission("subscriptions:cancel"))])
async def cancel(
    payload: CancelRequest, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> SubscriptionResponse:
    sub = await sub_svc.cancel(
        db,
        tenant_id=current_tenant_id() or user.tenant_id,
        at_period_end=payload.at_period_end,
        reason=payload.reason,
        actor_user_id=user.id,
    )
    return _serialise(sub)
