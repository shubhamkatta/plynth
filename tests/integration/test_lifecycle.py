"""Subscription state-machine + background-job tests (via direct service calls)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.tenant import Tenant
from app.services import subscription as sub_svc
from tests.conftest import product_id


async def _bootstrap() -> Tenant:
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = Tenant(product_id=pid, name="Lifecycle", slug="lifecycle", is_root=True)
            db.add(t)
            await db.flush()
            await sub_svc.start_trial(db, tenant_id=t.id, product_id=pid)
            return t


@pytest.mark.asyncio
async def test_enter_grace_then_suspend_after_expiry() -> None:
    tenant = await _bootstrap()

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            sub = await db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
            assert sub is not None
            sub.status = SubscriptionStatus.ACTIVE
            await sub_svc.enter_grace_period(db, subscription_id=sub.id)

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            sub = await db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
            assert sub.status == SubscriptionStatus.GRACE
            assert sub.grace_ends_at is not None and sub.grace_ends_at > datetime.now(UTC)

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            sub = await db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
            sub.grace_ends_at = datetime.now(UTC) - timedelta(hours=1)

    async with session_scope() as db:
        suspended = await sub_svc.suspend_if_grace_expired(db)
    assert suspended == 1

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            sub = await db.scalar(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
            assert sub.status == SubscriptionStatus.SUSPENDED
            assert sub.has_access is False


@pytest.mark.asyncio
async def test_suspend_sweep_skips_non_grace_subs() -> None:
    await _bootstrap()
    async with session_scope() as db:
        suspended = await sub_svc.suspend_if_grace_expired(db)
    assert suspended == 0
