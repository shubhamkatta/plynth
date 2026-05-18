"""Payment reminder dispatcher: idempotency + correct day-offset selection."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.invoice import Invoice, InvoiceStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.tasks import payment_reminders
from tests.conftest import product_id


async def _seed_open_invoice(due_in_days: int = 0, amount_cents: int = 2900) -> Tenant:
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = Tenant(product_id=pid, name="Reminder Co",
                       slug=f"reminder-{uuid4().hex[:6]}", is_root=True)
            db.add(t)
            await db.flush()
            owner = User(
                product_id=pid, tenant_id=t.id,
                email=f"billing+{t.slug}@example.com",
                password_hash="x", full_name="Owner", is_active=True,
            )
            db.add(owner)
            now = datetime.now(UTC)
            db.add(Invoice(
                product_id=pid, tenant_id=t.id, subscription_id=None,
                amount_cents=amount_cents, currency="USD",
                status=InvoiceStatus.OPEN,
                issued_at=now, due_at=now + timedelta(days=due_in_days),
                provider="mock",
                provider_invoice_id=f"in_{uuid4().hex[:10]}",
            ))
            return t


@pytest.mark.asyncio
async def test_reminder_sent_on_due_offsets() -> None:
    await _seed_open_invoice(due_in_days=3)
    async with session_scope() as db:
        sent = await payment_reminders.dispatch_due_reminders(db, now=datetime.now(UTC))
    assert sent == 1


@pytest.mark.asyncio
async def test_reminder_idempotent_same_day() -> None:
    await _seed_open_invoice(due_in_days=0)
    async with session_scope() as db:
        a = await payment_reminders.dispatch_due_reminders(db, now=datetime.now(UTC))
    async with session_scope() as db:
        b = await payment_reminders.dispatch_due_reminders(db, now=datetime.now(UTC))
    assert a == 1
    assert b == 0


@pytest.mark.asyncio
async def test_reminder_skipped_if_no_active_users() -> None:
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = Tenant(product_id=pid, name="Empty",
                       slug=f"empty-{uuid4().hex[:6]}", is_root=True)
            db.add(t)
            await db.flush()
            now = datetime.now(UTC)
            db.add(Invoice(
                product_id=pid, tenant_id=t.id,
                amount_cents=100, currency="USD",
                status=InvoiceStatus.OPEN, issued_at=now, due_at=now,
                provider="mock", provider_invoice_id=f"in_{uuid4().hex[:10]}",
            ))
    async with session_scope() as db:
        sent = await payment_reminders.dispatch_due_reminders(db, now=datetime.now(UTC))
    assert sent == 0
