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
