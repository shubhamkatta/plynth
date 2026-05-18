"""Direct service-level credit tests (bypass HTTP)."""

from decimal import Decimal

import pytest

from app.core.database import session_scope
from app.core.exceptions import InsufficientCredits
from app.core.tenant import bypass_product, bypass_tenant
from app.models.tenant import Tenant
from app.services import credit
from tests.conftest import product_id


async def _make_tenant(slug: str = "credits-test") -> Tenant:
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = Tenant(product_id=pid, name="Credits Test", slug=slug, is_root=True)
            db.add(t)
            await db.flush()
            return t


@pytest.mark.asyncio
async def test_grant_consume_balance_consistent() -> None:
    tenant = await _make_tenant()
    pid = product_id("producta")
    feat = "credits.ai_completion"
    async with session_scope() as db:
        await credit.grant(db, tenant_id=tenant.id, product_id=pid,
                           feature_key=feat, amount=Decimal("100"))
    async with session_scope() as db:
        w = await credit.consume(db, tenant_id=tenant.id, product_id=pid,
                                 feature_key=feat, amount=Decimal("40"))
        assert w.balance == Decimal("60")
    async with session_scope() as db:
        with pytest.raises(InsufficientCredits):
            await credit.consume(db, tenant_id=tenant.id, product_id=pid,
                                 feature_key=feat, amount=Decimal("999"))


@pytest.mark.asyncio
async def test_idempotent_grant_via_reference() -> None:
    tenant = await _make_tenant("dedupe-grant")
    pid = product_id("producta")
    feat = "credits.ai_completion"
    for _ in range(3):
        async with session_scope() as db:
            await credit.grant(
                db, tenant_id=tenant.id, product_id=pid, feature_key=feat,
                amount=Decimal("10"), reference="invoice:abc",
            )
    async with session_scope() as db:
        w = await credit._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=pid, feature_key=feat,
        )
    assert w.balance == Decimal("10")


@pytest.mark.asyncio
async def test_idempotent_consume_via_reference() -> None:
    tenant = await _make_tenant("dedupe-consume")
    pid = product_id("producta")
    feat = "credits.ai_completion"
    async with session_scope() as db:
        await credit.grant(db, tenant_id=tenant.id, product_id=pid,
                           feature_key=feat, amount=Decimal("50"))
    for _ in range(4):
        async with session_scope() as db:
            await credit.consume(
                db, tenant_id=tenant.id, product_id=pid, feature_key=feat,
                amount=Decimal("10"), reference="req:xyz",
            )
    async with session_scope() as db:
        w = await credit._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=pid, feature_key=feat,
        )
    assert w.balance == Decimal("40")


@pytest.mark.asyncio
async def test_period_reset_zeros_balance() -> None:
    tenant = await _make_tenant("period-reset")
    pid = product_id("producta")
    feat = "credits.ai_completion"
    async with session_scope() as db:
        await credit.grant(db, tenant_id=tenant.id, product_id=pid,
                           feature_key=feat, amount=Decimal("75"))
    async with session_scope() as db:
        w = await credit.reset_period(db, tenant_id=tenant.id, product_id=pid, feature_key=feat)
    assert w.balance == Decimal("0")
