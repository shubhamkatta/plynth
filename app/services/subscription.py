"""Subscription lifecycle.

Every subscription belongs to a (product, tenant). Calls take an explicit
`product_id`; internal helpers derive it from the loaded Subscription.

State machine:
  trial → active → past_due → grace → suspended
                       ↘ active (paid)
  any → cancelled (voluntary) → expired (after period_end)
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.tenant import bypass_product, bypass_tenant
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.tenant import Tenant
from app.providers.billing import get_billing_provider
from app.services import audit, credit
from app.services import plan as plan_svc


async def start_trial(
    db: AsyncSession, *, tenant_id: UUID, product_id: UUID, plan_code: str | None = None
) -> Subscription:
    """Bootstrap subscription on a free trial of the cheapest public plan
    (or a specified one) within the product."""
    with bypass_product(), bypass_tenant():
        if await db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)):
            raise Conflict("subscription already exists")

        if plan_code:
            plan = await plan_svc.get_by_code(db, product_id=product_id, code=plan_code)
        else:
            plans = await plan_svc.list_plans(db, product_id=product_id)
            if not plans:
                raise ValidationFailed("no public plans available; seed plans first")
            plan = min(plans, key=lambda p: p.price_cents)

        now = datetime.now(UTC)
        trial_days = plan.trial_days or settings.default_trial_days
        sub = Subscription(
            product_id=product_id,
            tenant_id=tenant_id,
            plan_id=plan.id,
            status=SubscriptionStatus.TRIAL,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            trial_end=now + timedelta(days=trial_days),
            provider="mock",
        )
        db.add(sub)
        await db.flush()
        await credit.grant_plan_credits(
            db, tenant_id=tenant_id, product_id=product_id, plan=plan,
            reference=f"trial:{sub.id}",
        )
        await audit.record(
            db, action="subscription.trial_started",
            resource_type="subscription", resource_id=sub.id,
            tenant_id=tenant_id, product_id=product_id,
            diff={"plan": plan.code, "trial_days": trial_days},
        )
    return sub


async def purchase(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    plan_code: str,
    payment_method_token: str | None,
    actor_user_id: UUID | None,
    idempotency_key: str | None,
) -> Subscription:
    """Upsert an ACTIVE subscription on `plan_code` for the tenant.

    Two paths:
    - Existing sub (trial / past_due / grace / cancelled) → replace plan
      and flip to ACTIVE. The on-trial → paid case is the common one.
    - No sub yet (admin-created tenant, or product where start_trial
      wasn't called) → create one. Saves an extra "start trial first" UX
      detour just to immediately purchase.
    """
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("tenant missing")
    plan = await plan_svc.get_by_code(db, product_id=tenant.product_id, code=plan_code)

    provider = get_billing_provider()
    price_id = plan.provider_refs.get(provider.name)
    if not price_id and provider.name != "mock":
        raise ValidationFailed(f"plan {plan.code} has no price for provider {provider.name}")

    customer = await provider.ensure_customer(
        tenant_id=str(tenant_id), email=f"billing@{tenant.slug}",
    )
    p_sub = await provider.create_subscription(
        customer_id=customer.id,
        price_id=price_id or plan.code,
        trial_days=0,
        payment_method_token=payment_method_token,
        idempotency_key=idempotency_key,
    )

    with bypass_product(), bypass_tenant():
        sub = await db.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
    is_new = sub is None
    if is_new:
        sub = Subscription(
            product_id=tenant.product_id,
            tenant_id=tenant_id,
            plan_id=plan.id,
        )
        db.add(sub)

    sub.plan = plan
    sub.status = SubscriptionStatus.ACTIVE
    sub.current_period_start = p_sub.current_period_start
    sub.current_period_end = p_sub.current_period_end
    sub.trial_end = None
    sub.grace_ends_at = None
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.provider = provider.name
    sub.provider_customer_id = customer.id
    sub.provider_subscription_id = p_sub.id
    await db.flush()
    await credit.grant_plan_credits(
        db, tenant_id=tenant_id, product_id=tenant.product_id, plan=plan,
        reference=f"period:{p_sub.id}:{p_sub.current_period_start.date()}",
    )
    await audit.record(
        db, action="subscription.purchase" if not is_new else "subscription.start",
        actor_user_id=actor_user_id,
        resource_type="subscription", resource_id=sub.id,
        tenant_id=tenant_id, product_id=tenant.product_id,
        diff={"plan": plan.code, "provider": provider.name, "created": is_new},
    )
    return sub


async def change_plan(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    new_plan_code: str,
    proration: bool,
    actor_user_id: UUID | None,
    idempotency_key: str | None,
) -> Subscription:
    sub = await _get_or_raise(db, tenant_id)
    new_plan = await plan_svc.get_by_code(db, product_id=sub.product_id, code=new_plan_code)
    old_plan = await db.get(Plan, sub.plan_id)

    if old_plan and old_plan.id == new_plan.id:
        raise Conflict("subscription already on this plan")

    is_upgrade = new_plan.price_cents > (old_plan.price_cents if old_plan else 0)
    provider = get_billing_provider()

    if sub.provider_subscription_id:
        price_id = new_plan.provider_refs.get(provider.name, new_plan.code)
        p_sub = await provider.change_subscription(
            subscription_id=sub.provider_subscription_id,
            new_price_id=price_id,
            proration=proration,
            idempotency_key=idempotency_key,
        )
        sub.current_period_start = p_sub.current_period_start
        sub.current_period_end = p_sub.current_period_end

    sub.plan = new_plan
    await db.flush()
    await audit.record(
        db,
        action="subscription.upgrade" if is_upgrade else "subscription.downgrade",
        actor_user_id=actor_user_id,
        resource_type="subscription",
        resource_id=sub.id,
        tenant_id=tenant_id,
        product_id=sub.product_id,
        diff={
            "from": old_plan.code if old_plan else None,
            "to": new_plan.code,
            "proration": proration,
        },
    )
    return sub


async def cancel(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    at_period_end: bool,
    reason: str | None,
    actor_user_id: UUID | None,
) -> Subscription:
    sub = await _get_or_raise(db, tenant_id)
    provider = get_billing_provider()
    if sub.provider_subscription_id:
        await provider.cancel_subscription(
            subscription_id=sub.provider_subscription_id, at_period_end=at_period_end
        )
    now = datetime.now(UTC)
    if at_period_end:
        sub.cancel_at_period_end = True
    else:
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = now
    await db.flush()
    await audit.record(
        db, action="subscription.cancel", actor_user_id=actor_user_id,
        resource_type="subscription", resource_id=sub.id,
        tenant_id=tenant_id, product_id=sub.product_id,
        diff={"at_period_end": at_period_end, "reason": reason},
    )
    return sub


async def enter_grace_period(db: AsyncSession, *, subscription_id: UUID) -> Subscription:
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        raise NotFound("subscription not found")
    if sub.status in (SubscriptionStatus.SUSPENDED, SubscriptionStatus.CANCELLED):
        return sub
    sub.status = SubscriptionStatus.GRACE
    sub.grace_ends_at = datetime.now(UTC) + timedelta(days=settings.grace_period_days)
    await db.flush()
    await audit.record(
        db, action="subscription.grace_started", resource_type="subscription",
        resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
        diff={"grace_ends_at": sub.grace_ends_at.isoformat()},
    )
    return sub


async def suspend_if_grace_expired(db: AsyncSession) -> int:
    """Cross-product sweep: move every subscription whose grace has lapsed."""
    now = datetime.now(UTC)
    with bypass_product(), bypass_tenant():
        candidates = (
            await db.scalars(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.GRACE,
                    Subscription.grace_ends_at <= now,
                )
            )
        ).all()
        for sub in candidates:
            sub.status = SubscriptionStatus.SUSPENDED
            await audit.record(
                db, action="subscription.suspended", resource_type="subscription",
                resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
            )
    return len(candidates)


async def _get_or_raise(db: AsyncSession, tenant_id: UUID) -> Subscription:
    with bypass_product(), bypass_tenant():
        sub = await db.scalar(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(Subscription.tenant_id == tenant_id)
        )
    if sub is None:
        raise NotFound("subscription not found")
    return sub


async def get_for_tenant(db: AsyncSession, tenant_id: UUID) -> Subscription:
    return await _get_or_raise(db, tenant_id)
