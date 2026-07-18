"""Mayva plan catalog + component entitlements + ai_messages credit grants.

Drives the `scripts.seed_mayva` helpers against a throwaway `mayva`-shaped
product and asserts the contract the Mayva app reads:

- plan catalog (essentials / practice / concierge / clinic) with the right
  ai_messages grants;
- the 9 components gated by `required_plan_codes`;
- a Practice-tier tenant's effective component map (the /auth/me shape);
- the ai_messages wallet balance + consume/insufficient behaviour.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.database import session_scope
from app.core.exceptions import InsufficientCredits
from app.core.tenant import bypass_product, bypass_tenant
from app.models.product import Product, ProductStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import component as component_svc
from app.services import credit as credit_svc
from app.services import rbac
from scripts import seed_mayva


async def _bootstrap_mayva_product() -> tuple[Product, Tenant, User]:
    """Create a fresh mayva-shaped product + dev tenant + user, then run the
    catalog seed helpers against it."""
    slug = f"mayvacat-{uuid4().hex[:8]}"
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = Product(
                name="Mayva Catalog Test", slug=slug,
                status=ProductStatus.ACTIVE, is_active=True,
            )
            db.add(product)
            await db.flush()
            await rbac.ensure_system_roles_for_product(db, product_id=product.id)
            tenant = Tenant(
                product_id=product.id, name="Test Practice",
                slug=seed_mayva.DEV_TENANT_SLUG, is_root=True,
            )
            db.add(tenant)
            await db.flush()
            user = User(
                product_id=product.id, tenant_id=tenant.id,
                email=f"gate0@{slug}.example.com", password_hash="x",
                full_name="Gate Zero", is_active=True, is_verified=True,
            )
            db.add(user)
            await db.flush()

        plans = await seed_mayva._ensure_plans(db, product.id)
        await seed_mayva._ensure_components(db, product.id)
        await seed_mayva._ensure_dev_subscription(
            db, product_id=product.id, tenant=tenant,
            plan=plans[seed_mayva.DEV_PLAN_CODE],
        )
    return product, tenant, user


# ---------------------------------------------------------------------------
# Catalog spec invariants (the contract, independent of the DB)
# ---------------------------------------------------------------------------

def test_plan_catalog_ai_message_grants() -> None:
    grants = {p["code"]: p["ai_messages"] for p in seed_mayva.PLANS}
    assert grants["essentials"] == Decimal("0")
    assert grants["practice"] == Decimal("500")
    assert grants["concierge"] == Decimal("2000")
    assert grants["clinic"] is None  # relies on unlimited_ai component


def test_component_plan_gating_spec() -> None:
    gates = {c["code"]: c["required_plan_codes"] for c in seed_mayva.COMPONENTS}
    assert set(gates) == {
        "ai_receptionist", "voice_notes", "payment_followups", "weekly_digest",
        "followup_agent", "analytics", "multi_practitioner", "admin_roles",
        "unlimited_ai",
    }
    # Practice-and-up components.
    for code in ("ai_receptionist", "voice_notes", "payment_followups", "weekly_digest"):
        assert gates[code] == ["practice", "concierge", "clinic"]
    # Concierge-and-up.
    for code in ("followup_agent", "analytics"):
        assert gates[code] == ["concierge", "clinic"]
    # Clinic-only.
    for code in ("multi_practitioner", "admin_roles", "unlimited_ai"):
        assert gates[code] == ["clinic"]


# ---------------------------------------------------------------------------
# End-to-end against a seeded product
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plans_and_components_created() -> None:
    product, _tenant, _user = await _bootstrap_mayva_product()
    async with session_scope() as db:
        comps = await component_svc.list_components(db, product_id=product.id)
    assert {c.code for c in comps} == {
        "ai_receptionist", "voice_notes", "payment_followups", "weekly_digest",
        "followup_agent", "analytics", "multi_practitioner", "admin_roles",
        "unlimited_ai",
    }


@pytest.mark.asyncio
async def test_practice_tenant_effective_components() -> None:
    """A Practice-tier tenant sees the four Practice components enabled and
    the five higher-tier ones gated off — the /auth/me components map."""
    _product, _tenant, user = await _bootstrap_mayva_product()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            db_user = await db.get(User, user.id)
        rows = await component_svc.user_effective_components(db, user=db_user)
    effective = {c.code: is_enabled for (c, is_enabled, _s, _r) in rows}
    assert effective == {
        "ai_receptionist": True,
        "voice_notes": True,
        "payment_followups": True,
        "weekly_digest": True,
        "followup_agent": False,
        "analytics": False,
        "multi_practitioner": False,
        "admin_roles": False,
        "unlimited_ai": False,
    }


@pytest.mark.asyncio
async def test_practice_tenant_gets_500_ai_message_credits() -> None:
    _product, tenant, _user = await _bootstrap_mayva_product()
    pid = _product.id
    async with session_scope() as db:
        wallet = await credit_svc._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=pid,
            feature_key=seed_mayva.AI_FEATURE_KEY,
        )
        assert wallet.balance == Decimal("500")

    # Consuming an AI message debits the wallet.
    async with session_scope() as db:
        w = await credit_svc.consume(
            db, tenant_id=tenant.id, product_id=pid,
            feature_key=seed_mayva.AI_FEATURE_KEY, amount=Decimal("1"),
        )
        assert w.balance == Decimal("499")

    # Overdrawing the quota raises InsufficientCredits (the enforcement gate).
    async with session_scope() as db:
        with pytest.raises(InsufficientCredits):
            await credit_svc.consume(
                db, tenant_id=tenant.id, product_id=pid,
                feature_key=seed_mayva.AI_FEATURE_KEY, amount=Decimal("100000"),
            )


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    """Re-running the catalog seed doesn't double-grant credits or duplicate
    components."""
    product, tenant, _user = await _bootstrap_mayva_product()
    async with session_scope() as db:
        plans = await seed_mayva._ensure_plans(db, product.id)
        await seed_mayva._ensure_components(db, product.id)
        await seed_mayva._ensure_dev_subscription(
            db, product_id=product.id, tenant=tenant,
            plan=plans[seed_mayva.DEV_PLAN_CODE],
        )
    async with session_scope() as db:
        comps = await component_svc.list_components(db, product_id=product.id)
        wallet = await credit_svc._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=product.id,
            feature_key=seed_mayva.AI_FEATURE_KEY,
        )
    assert len(comps) == 9
    assert wallet.balance == Decimal("500")  # not 1000
