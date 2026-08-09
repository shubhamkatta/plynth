"""Marketing-site billing checkout.

`POST /billing/checkout` runs the purchase/subscribe path for a plan on the
authenticated caller's tenant and returns the provider's hosted authorization
URL (Razorpay `short_url`) so the marketing site can redirect the browser to
pay. Free/$0 plans need no payment and return `url: null` + `status: active`.

Same auth surface as `POST /subscription/purchase`: Bearer JWT (product from
the `pid` claim; `X-Product-Slug`, if present, must match) + the
`subscriptions:purchase` permission.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, actor_id, get_idempotency_key, require_permission
from app.core.tenant import current_tenant_id
from app.schemas.billing import CheckoutRequest, CheckoutResponse
from app.services import subscription as sub_svc

router = APIRouter()


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(require_permission("subscriptions:purchase"))],
)
async def checkout(
    payload: CheckoutRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
) -> CheckoutResponse:
    sub, authorization_url = await sub_svc.checkout(
        db,
        tenant_id=current_tenant_id() or user.tenant_id,
        plan_code=payload.plan_code,
        actor_user_id=actor_id(user),
        idempotency_key=idempotency_key,
    )
    if authorization_url is None:
        # Free/$0 plan: already active, nothing to authorize.
        return CheckoutResponse(url=None, status=sub.status.value)
    return CheckoutResponse(
        url=authorization_url,
        subscription_id=sub.provider_subscription_id,
    )
