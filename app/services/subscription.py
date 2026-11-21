"""Subscription lifecycle.

Every subscription belongs to a (product, tenant). Calls take an explicit
`product_id`; internal helpers derive it from the loaded Subscription.

State machine:
  trial → active → past_due → grace → suspended
                       ↘ active (paid)
  any → cancelled (voluntary) → expired (after period_end)
"""

from datetime import UTC, datetime, timedelta
from math import ceil
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
        # Free plans (price_cents=0) skip the trial entirely → status ACTIVE,
        # trial_end NULL, current_period_end far in the future. Without this
        # branch a $0 plan with trial_days=0 would fall through `or
        # settings.default_trial_days` and silently get a 14-day trial that
        # later flows into GRACE / SUSPENDED — surfacing as "Free plan expired
        # after two weeks".
        if plan.price_cents == 0:
            status = SubscriptionStatus.ACTIVE
            trial_days = 0
            trial_end: datetime | None = None
            current_period_end = now + timedelta(days=365 * 100)
        else:
            status = SubscriptionStatus.TRIAL
            trial_days = plan.trial_days if plan.trial_days else settings.default_trial_days
            trial_end = now + timedelta(days=trial_days)
            current_period_end = now + timedelta(days=30)
        sub = Subscription(
            product_id=product_id,
            tenant_id=tenant_id,
            plan_id=plan.id,
            status=status,
            current_period_start=now,
            current_period_end=current_period_end,
            trial_end=trial_end,
            provider="mock",
        )
        db.add(sub)
        await db.flush()
        await credit.grant_plan_credits(
            db, tenant_id=tenant_id, product_id=product_id, plan=plan,
            reference=f"trial:{sub.id}",
        )
        await audit.record(
            db, action=(
                "subscription.activated_free"
                if plan.price_cents == 0
                else "subscription.trial_started"
            ),
            resource_type="subscription", resource_id=sub.id,
            tenant_id=tenant_id, product_id=product_id,
            diff={"plan": plan.code, "trial_days": trial_days, "status": status.value},
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
    customer_email: str | None = None,
) -> tuple[Subscription, str | None]:
    """Upsert an ACTIVE subscription on `plan_code` for the tenant.

    Returns ``(subscription, authorization_url)``. ``authorization_url`` is
    the provider's hosted redirect URL the customer must visit to authorize +
    pay (Razorpay's subscription ``short_url``); it is ``None`` for free/$0
    plans and for providers/paths that don't produce a redirect.

    Two paths:
    - Existing sub (trial / past_due / grace / cancelled) → replace plan
      and flip to ACTIVE. The on-trial → paid case is the common one.
    - No sub yet (admin-created tenant, or product where start_trial
      wasn't called) → create one. Saves an extra "start trial first" UX
      detour just to immediately purchase.

    Free/$0 plans skip the provider entirely — there's nothing to charge, so
    we never mint a provider subscription (a $0 Razorpay plan has no plan_id)
    and activate directly.

    Card-on-file / UPI-AutoPay free trial (paid plans)
    --------------------------------------------------
    The customer authorizes a recurring mandate at checkout but is NOT charged
    during the trial; the first deduction happens automatically at trial end.
    The provider subscription is therefore created with a *future* ``start_at``
    (``trial_days`` in the neutral interface), so the mandate is authorized now
    while the first invoice lands ~``trial_days`` later. Combined timeline:

        register (t0)       → start_trial → local TRIAL, trial_end = t0 + 14d
        checkout (t0..t1)   → this call: Razorpay sub with start_at = trial_end
                              (mandate authorized, NOT charged); local stays
                              TRIAL, provider ids attached
        trial_end (~t0+14d) → Razorpay raises the first invoice and charges
                              ONCE; the subscription.charged/activated webhook
                              flips local status → ACTIVE

    Reconciliation: if register→start_trial already opened a local trial, we
    honour its REMAINING days rather than starting a second one — the customer
    sees ONE ~14-day trial and is charged once, after it. With no prior local
    trial (free/active plan, or an admin-created tenant with no subscription) we
    open a fresh trial of the plan's length.
    """
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("tenant missing")
    plan = await plan_svc.get_by_code(db, product_id=tenant.product_id, code=plan_code)

    provider = get_billing_provider()
    is_free = plan.price_cents == 0
    now = datetime.now(UTC)

    # Load any existing subscription BEFORE minting the provider subscription —
    # we need to know whether a local trial is already running so the
    # provider-level trial (Razorpay start_at) and the plynth-level trial line
    # up into a single trial instead of stacking.
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
    is_new = existing is None

    # ---- Trial derivation (the single-trial timeline) ----------------------
    if is_free:
        # $0 plan: no mandate, no charge, no trial.
        trial_days = 0
        trial_end: datetime | None = None
    elif (
        existing is not None
        and existing.status == SubscriptionStatus.TRIAL
        and existing.trial_end is not None
        and existing.trial_end > now
    ):
        # Already on a local trial → defer the first charge to its END so we
        # don't stack a second trial. ceil keeps the mandate's start_at on the
        # far side of the existing trial_end (day resolution).
        trial_end = existing.trial_end
        trial_days = max(1, ceil((trial_end - now).total_seconds() / 86_400))
    else:
        # No prior trial → open a fresh one of the plan's length.
        trial_days = plan.trial_days if plan.trial_days else settings.default_trial_days
        trial_end = now + timedelta(days=trial_days)

    customer = None
    p_sub = None
    authorization_url: str | None = None
    if not is_free:
        price_id = plan.provider_refs.get(provider.name)
        if not price_id and provider.name != "mock":
            raise ValidationFailed(
                f"plan {plan.code} has no price for provider {provider.name}"
            )
        billing_email = customer_email or tenant.slug
        customer = await provider.ensure_customer(
            tenant_id=str(tenant_id), email=billing_email,
        )
        p_sub = await provider.create_subscription(
            customer_id=customer.id,
            price_id=price_id or plan.code,
            # Defer the first charge to trial end (was hardcoded 0, which made
            # Razorpay charge immediately on mandate authorization).
            trial_days=trial_days,
            payment_method_token=payment_method_token,
            idempotency_key=idempotency_key,
        )
        authorization_url = p_sub.authorization_url

    if existing is None:
        sub = Subscription(
            product_id=tenant.product_id,
            tenant_id=tenant_id,
            plan_id=plan.id,
        )
        db.add(sub)
    else:
        sub = existing

    sub.plan = plan
    sub.grace_ends_at = None
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.provider = provider.name if p_sub else "mock"
    sub.provider_customer_id = customer.id if customer else None
    sub.provider_subscription_id = p_sub.id if p_sub else None
    if is_free:
        # Active immediately, never expires (no charge to defer).
        sub.status = SubscriptionStatus.ACTIVE
        sub.trial_end = None
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=365 * 100)
    else:
        # On trial until the first charge; the subscription webhook flips this
        # to ACTIVE once Razorpay confirms the first deduction at trial end.
        assert trial_end is not None  # paid branch always derives a trial_end
        sub.status = SubscriptionStatus.TRIAL
        sub.trial_end = trial_end
        sub.current_period_start = now
        sub.current_period_end = trial_end
    await db.flush()
    credit_reference = (
        f"period:{p_sub.id}:{p_sub.current_period_start.date()}"
        if p_sub
        else f"free:{sub.id}:{plan.code}"
    )
    await credit.grant_plan_credits(
        db, tenant_id=tenant_id, product_id=tenant.product_id, plan=plan,
        reference=credit_reference,
    )
    await audit.record(
        db, action="subscription.purchase" if not is_new else "subscription.start",
        actor_user_id=actor_user_id,
        resource_type="subscription", resource_id=sub.id,
        tenant_id=tenant_id, product_id=tenant.product_id,
        diff={
            "plan": plan.code,
            "provider": sub.provider,
            "created": is_new,
            "status": sub.status.value,
            "trial_days": trial_days,
            "first_charge_at": trial_end.isoformat() if trial_end else None,
        },
    )
    return sub, authorization_url


async def checkout(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    plan_code: str,
    actor_user_id: UUID | None,
    idempotency_key: str | None,
    customer_email: str | None = None,
) -> tuple[Subscription, str | None]:
    """Marketing-site checkout: run the purchase/subscribe path for `plan_code`
    on the caller's tenant and surface the provider's hosted authorization URL
    (Razorpay ``short_url``) so the site can redirect the browser to pay.

    Free/$0 plans need no payment — they activate immediately and the returned
    URL is ``None``. Reuses :func:`purchase`; adds a checkout audit trail."""
    sub, authorization_url = await purchase(
        db,
        tenant_id=tenant_id,
        plan_code=plan_code,
        payment_method_token=None,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        customer_email=customer_email,
    )
    await audit.record(
        db, action="billing.checkout", actor_user_id=actor_user_id,
        resource_type="subscription", resource_id=sub.id,
        tenant_id=tenant_id, product_id=sub.product_id,
        diff={"plan": plan_code, "has_redirect": authorization_url is not None},
    )
    return sub, authorization_url


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
    # Grant the new plan's credits on change — otherwise an upgrader receives the
    # new plan's component entitlements but a stale/empty credit wallet until the
    # next renewal (grant_plan_credits was previously only wired into
    # start_trial/purchase/renewal). The reference is scoped to
    # (subscription, new plan, current period), so re-changing to the same plan
    # within a period is a no-op and never double-grants.
    await credit.grant_plan_credits(
        db,
        tenant_id=tenant_id,
        product_id=sub.product_id,
        plan=new_plan,
        reference=f"change:{sub.id}:{new_plan.code}:{sub.current_period_start.date()}",
    )
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


async def expire_lapsed_trials(db: AsyncSession) -> int:
    """Cross-product sweep: end TRIALs that never converted.

    A TRIAL whose `trial_end` is more than `trial_expiry_buffer_days` in the
    past never received a `subscription.charged`/`activated` webhook — i.e. no
    mandate was authorized, or the first charge didn't happen. Without this the
    status stays TRIAL (which `has_access`) forever. Moves them to EXPIRED
    (access cut). Reversible: a late `subscription.charged` webhook flips an
    EXPIRED subscription back to ACTIVE via `handle_subscription_activated`.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.trial_expiry_buffer_days)
    with bypass_product(), bypass_tenant():
        candidates = (
            await db.scalars(
                select(Subscription).where(
                    Subscription.status == SubscriptionStatus.TRIAL,
                    Subscription.trial_end.is_not(None),
                    Subscription.trial_end <= cutoff,
                )
            )
        ).all()
        for sub in candidates:
            sub.status = SubscriptionStatus.EXPIRED
            await audit.record(
                db, action="subscription.trial_expired", resource_type="subscription",
                resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
                diff={
                    "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
                    "has_provider_subscription": sub.provider_subscription_id is not None,
                },
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
