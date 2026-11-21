"""Billing-side state changes: invoice handling, webhook dispatch."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import bypass_product, bypass_tenant
from app.models.invoice import Invoice, InvoiceStatus
from app.models.subscription import Subscription, SubscriptionStatus
from app.services import audit
from app.services import subscription as sub_svc


async def record_invoice(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    subscription_id: UUID | None,
    provider: str,
    provider_invoice_id: str,
    amount_cents: int,
    currency: str,
    status: InvoiceStatus,
    issued_at: datetime,
    due_at: datetime,
    hosted_url: str | None = None,
) -> Invoice:
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(Invoice).where(
                Invoice.provider == provider,
                Invoice.provider_invoice_id == provider_invoice_id,
            )
        )
        if existing:
            existing.status = status
            if status == InvoiceStatus.PAID and existing.paid_at is None:
                existing.paid_at = datetime.now(UTC)
            return existing

        invoice = Invoice(
            product_id=product_id,
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            provider=provider,
            provider_invoice_id=provider_invoice_id,
            amount_cents=amount_cents,
            currency=currency,
            status=status,
            issued_at=issued_at,
            due_at=due_at,
            hosted_invoice_url=hosted_url,
            paid_at=datetime.now(UTC) if status == InvoiceStatus.PAID else None,
        )
        db.add(invoice)
        await db.flush()
    return invoice


async def handle_payment_failed(db: AsyncSession, *, invoice_id: UUID) -> None:
    """Provider notified us a payment attempt failed. Bump retry counter,
    transition subscription to PAST_DUE; after the final retry, enter GRACE."""
    inv = await db.get(Invoice, invoice_id)
    if inv is None:
        return
    inv.attempt_count += 1
    inv.last_attempt_at = datetime.now(UTC)
    inv.next_attempt_at = inv.last_attempt_at + timedelta(days=3)

    if inv.subscription_id:
        sub = await db.get(Subscription, inv.subscription_id)
        if sub and sub.status not in (SubscriptionStatus.GRACE, SubscriptionStatus.SUSPENDED):
            if inv.attempt_count >= 3:
                await sub_svc.enter_grace_period(db, subscription_id=sub.id)
            else:
                sub.status = SubscriptionStatus.PAST_DUE
                await audit.record(
                    db, action="subscription.past_due", resource_type="subscription",
                    resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
                    diff={"attempt": inv.attempt_count},
                )


async def handle_subscription_activated(db: AsyncSession, *, subscription_id: UUID) -> None:
    """Provider notified us a subscription is now authorized/paid/active
    (Razorpay ``subscription.activated`` / ``.charged`` / ``.authenticated``).

    Flip it to ACTIVE and clear any grace window. Mirrors
    ``handle_payment_succeeded`` but is keyed off the subscription lifecycle
    rather than an invoice — this is how a checkout redirect (where the first
    charge happens on Razorpay's hosted page) confirms back to us. No-op if the
    subscription is already ACTIVE (idempotent under provider retries)."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        return
    # A late/out-of-order charge event must not resurrect a cancelled sub.
    if sub.status == SubscriptionStatus.CANCELLED:
        return
    if sub.status != SubscriptionStatus.ACTIVE:
        sub.status = SubscriptionStatus.ACTIVE
        sub.grace_ends_at = None
        await audit.record(
            db, action="subscription.reactivated", resource_type="subscription",
            resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
        )


async def handle_mandate_authorized(db: AsyncSession, *, subscription_id: UUID) -> None:
    """Razorpay `subscription.authenticated`: the customer authorized the
    mandate (no money moved yet on a card-on-file trial). Record it so the app
    can tell "trial, mandate in place" from "trial, never authorized" without
    flipping the status label early."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None or sub.meta.get("mandate_authorized_at"):
        return
    sub.meta = {**sub.meta, "mandate_authorized_at": datetime.now(UTC).isoformat()}
    await db.flush()


async def handle_subscription_pending(db: AsyncSession, *, subscription_id: UUID) -> None:
    """Razorpay `subscription.pending`: a charge failed and Razorpay is
    retrying → PAST_DUE (access kept). Only from ACTIVE/TRIAL."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None or sub.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
        return
    sub.status = SubscriptionStatus.PAST_DUE
    await db.flush()
    await audit.record(
        db, action="subscription.past_due", resource_type="subscription",
        resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
    )


async def handle_subscription_halted(db: AsyncSession, *, subscription_id: UUID) -> None:
    """Razorpay `subscription.halted`: retries exhausted → grace period (the
    hourly sweep suspends it when `grace_ends_at` passes)."""
    await sub_svc.enter_grace_period(db, subscription_id=subscription_id)


async def handle_subscription_cancelled(db: AsyncSession, *, subscription_id: UUID) -> None:
    """Razorpay `subscription.cancelled` (incl. cancel-at-cycle-end firing).
    Idempotent."""
    sub = await db.get(Subscription, subscription_id)
    if sub is None or sub.status == SubscriptionStatus.CANCELLED:
        return
    sub.status = SubscriptionStatus.CANCELLED
    sub.cancelled_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db, action="subscription.cancelled", resource_type="subscription",
        resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
        diff={"source": "provider_webhook"},
    )


async def handle_payment_succeeded(db: AsyncSession, *, invoice_id: UUID) -> None:
    inv = await db.get(Invoice, invoice_id)
    if inv is None:
        return
    inv.status = InvoiceStatus.PAID
    inv.paid_at = datetime.now(UTC)
    if inv.subscription_id:
        sub = await db.get(Subscription, inv.subscription_id)
        if sub and sub.status in (
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.GRACE,
            SubscriptionStatus.SUSPENDED,
        ):
            sub.status = SubscriptionStatus.ACTIVE
            sub.grace_ends_at = None
            await audit.record(
                db, action="subscription.reactivated", resource_type="subscription",
                resource_id=sub.id, tenant_id=sub.tenant_id, product_id=sub.product_id,
            )
