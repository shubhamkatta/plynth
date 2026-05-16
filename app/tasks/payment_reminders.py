"""Payment reminders.

Selects open invoices that are due soon or overdue, dispatches notifications
through `app.providers.notifications`. Idempotent per (invoice, day) via a
Redis SETNX guard.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.tenant import bypass_tenant
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.providers import notifications

REMINDER_OFFSETS_DAYS = [-3, 0, 3, 7]  # before due, on due, after due


async def _already_sent(invoice_id, offset: int) -> bool:
    key = f"reminder:{invoice_id}:{offset}"
    # SETNX with 30-day expiry.
    return not await get_redis().set(key, "1", nx=True, ex=60 * 60 * 24 * 30)


async def dispatch_due_reminders(db: AsyncSession, *, now: datetime) -> int:
    sent = 0
    with bypass_tenant():
        invoices = (
            await db.scalars(
                select(Invoice).where(Invoice.status.in_([InvoiceStatus.OPEN, InvoiceStatus.DRAFT]))
            )
        ).all()

        for inv in invoices:
            days_to_due = (inv.due_at.date() - now.date()).days
            if days_to_due in REMINDER_OFFSETS_DAYS:
                if await _already_sent(inv.id, days_to_due):
                    continue
                tenant = await db.get(Tenant, inv.tenant_id)
                owner = await db.scalar(
                    select(User).where(User.tenant_id == inv.tenant_id, User.is_active.is_(True))
                )
                if tenant is None or owner is None:
                    continue
                await notifications.send_email(
                    to=owner.email,
                    template="payment_reminder",
                    context={
                        "tenant": tenant.name,
                        "amount_cents": inv.amount_cents,
                        "currency": inv.currency,
                        "due_at": inv.due_at.isoformat(),
                        "days_to_due": days_to_due,
                        "hosted_url": inv.hosted_invoice_url,
                    },
                )
                sent += 1
    return sent


def next_reminder_at(due_at: datetime, today: datetime) -> datetime | None:
    """Helper: next reminder date for an invoice, or None if past final offset."""
    for offset in REMINDER_OFFSETS_DAYS:
        target = due_at + timedelta(days=offset)
        if target.date() >= today.date():
            return target
    return None
