"""SELECT … FOR UPDATE on a credit wallet serialises concurrent debits —
total debited never exceeds the starting balance."""

import asyncio
from decimal import Decimal

import pytest

from app.core.database import session_scope
from app.core.exceptions import InsufficientCredits
from app.core.tenant import bypass_product, bypass_tenant
from app.models.tenant import Tenant
from app.services import credit
from tests.conftest import product_id


async def _make_tenant_with_balance(starting: Decimal) -> Tenant:
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = Tenant(product_id=pid, name="Conc Co", slug="conc-co", is_root=True)
            db.add(t)
            await db.flush()
            await credit.grant(
                db, tenant_id=t.id, product_id=pid,
                feature_key="credits.ai_completion", amount=starting,
            )
            return t


@pytest.mark.asyncio
async def test_concurrent_consume_never_overdraws() -> None:
    tenant = await _make_tenant_with_balance(Decimal("100"))
    pid = product_id("producta")

    async def consume_one() -> bool:
        async with session_scope() as db:
            try:
                await credit.consume(
                    db, tenant_id=tenant.id, product_id=pid,
                    feature_key="credits.ai_completion", amount=Decimal("10"),
                )
                return True
            except InsufficientCredits:
                return False

    results = await asyncio.gather(*(consume_one() for _ in range(20)))
    succeeded = sum(results)
    assert succeeded == 10

    async with session_scope() as db:
        wallet = await credit._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=pid, feature_key="credits.ai_completion",
        )
    assert wallet.balance == Decimal("0")
