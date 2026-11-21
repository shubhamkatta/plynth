"""Monthly credit refill sweep (credit.refill_due_wallets).

Plan credits used to be one-off grants. The sweep makes them a monthly allowance:
when a wallet's period has ended it expires leftovers and grants the plan amount,
for subscriptions that still have access, idempotently.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.credit import CreditEntryType, CreditLedger, CreditWallet
from app.models.plan import BillingInterval, Plan, PlanFeature
from app.models.subscription import Subscription, SubscriptionStatus
from app.services import credit as credit_svc
from tests.conftest import product_id, register_tenant

KEY = "wa_messages"
MONTHLY = Decimal("100")


async def _setup(
    client: AsyncClient, *, interval: BillingInterval = BillingInterval.MONTH,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    trial_end: datetime | None = None, leftover: Decimal = Decimal("30"),
    wallet_age_days: int = 40,
):
    """A tenant on a plan granting MONTHLY `wa_messages`, with a wallet holding
    `leftover` credits whose first period (from creation) ended already."""
    slug = f"rf-{uuid4().hex[:8]}"
    await register_tenant(client, slug=slug)
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            plan = Plan(
                product_id=pid, code=f"refill-{uuid4().hex[:6]}", name="Refill test",
                price_cents=7900, interval=interval, trial_days=30,
                is_public=False, provider_refs={},
            )
            db.add(plan)
            await db.flush()
            db.add(PlanFeature(product_id=pid, plan_id=plan.id, feature_key=KEY,
                               limit_value=None, credit_amount=MONTHLY))
            sub = await db.scalar(
                select(Subscription).where(Subscription.tenant.has(slug=slug))
            )
            sub.plan_id = plan.id
            sub.status = status
            sub.trial_end = trial_end
            tenant_id = sub.tenant_id
            await db.flush()
        wallet = await credit_svc.grant(
            db, tenant_id=tenant_id, product_id=pid, feature_key=KEY,
            amount=leftover, reason="seed", reference=f"seed:{uuid4().hex}",
        )
        with bypass_product(), bypass_tenant():
            wallet.created_at = datetime.now(UTC) - timedelta(days=wallet_age_days)
            wallet.period_end = None
    return tenant_id, wallet.id


async def _wallet(wallet_id):
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            w = await db.get(CreditWallet, wallet_id)
            entries = (await db.scalars(
                select(CreditLedger).where(CreditLedger.wallet_id == wallet_id)
                .order_by(CreditLedger.created_at)
            )).all()
            return w.balance, w.period_end, [(e.entry_type, e.amount) for e in entries]


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", [BillingInterval.MONTH, BillingInterval.YEAR])
async def test_due_wallet_expires_leftovers_and_grants_monthly_amount(
    client: AsyncClient, interval: BillingInterval
) -> None:
    """Both monthly AND yearly plans get a monthly allowance."""
    _tenant, wid = await _setup(client, interval=interval)
    async with session_scope() as db:
        assert await credit_svc.refill_due_wallets(db) >= 1
    balance, period_end, entries = await _wallet(wid)
    assert balance == MONTHLY                                  # leftover 30 expired, 100 granted
    assert (CreditEntryType.EXPIRY, Decimal("-30")) in entries
    assert (CreditEntryType.GRANT, MONTHLY) in entries
    assert period_end > datetime.now(UTC) + timedelta(days=25)  # next period ~30d out


@pytest.mark.asyncio
async def test_refill_is_idempotent_and_not_early(client: AsyncClient) -> None:
    _t, wid = await _setup(client)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    after_first = await _wallet(wid)
    # Immediately again: period was advanced, so nothing happens.
    async with session_scope() as db:
        assert await credit_svc.refill_due_wallets(db) == 0
    assert await _wallet(wid) == after_first

    # A wallet whose period is still running is untouched.
    _t2, wid2 = await _setup(client, wallet_age_days=5)
    before = await _wallet(wid2)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    assert await _wallet(wid2) == before


@pytest.mark.asyncio
async def test_refill_skips_subscriptions_without_access(client: AsyncClient) -> None:
    _t, wid = await _setup(client, status=SubscriptionStatus.SUSPENDED)
    _t2, wid2 = await _setup(client, status=SubscriptionStatus.EXPIRED)
    b1, b2 = await _wallet(wid), await _wallet(wid2)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    assert await _wallet(wid) == b1 and await _wallet(wid2) == b2


@pytest.mark.asyncio
async def test_refill_skips_a_trial_that_never_converted(client: AsyncClient) -> None:
    """TRIAL past trial_end has not paid: no free month before the expiry sweep."""
    past = datetime.now(UTC) - timedelta(days=2)
    _t, wid = await _setup(client, status=SubscriptionStatus.TRIAL, trial_end=past)
    before = await _wallet(wid)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    assert await _wallet(wid) == before

    # ...but a trial still running (or a converted one) is refilled normally.
    future = datetime.now(UTC) + timedelta(days=5)
    _t2, wid2 = await _setup(client, status=SubscriptionStatus.TRIAL, trial_end=future)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    assert (await _wallet(wid2))[0] == MONTHLY


@pytest.mark.asyncio
async def test_refill_after_long_downtime_grants_once(client: AsyncClient) -> None:
    """No catch-up stacking: a wallet 100 days overdue gets ONE month, not three."""
    _t, wid = await _setup(client, wallet_age_days=130)
    async with session_scope() as db:
        await credit_svc.refill_due_wallets(db)
    assert (await _wallet(wid))[0] == MONTHLY
