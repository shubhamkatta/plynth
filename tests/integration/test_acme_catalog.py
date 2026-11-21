"""Acme plan catalog + component entitlements + ai_messages credit grants.

Drives the `scripts.seed_acme` helpers against a throwaway `acme`-shaped
product and asserts the contract the Acme app reads:

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
from app.models.plan import BillingInterval, Plan
from app.models.product import Product, ProductStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import component as component_svc
from app.services import credit as credit_svc
from app.services import rbac
from scripts import seed_acme


async def _bootstrap_acme_product() -> tuple[Product, Tenant, User]:
    """Create a fresh acme-shaped product + dev tenant + user, then run the
    catalog seed helpers against it."""
    slug = f"acmecat-{uuid4().hex[:8]}"
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = Product(
                name="Acme Catalog Test", slug=slug,
                status=ProductStatus.ACTIVE, is_active=True,
            )
            db.add(product)
            await db.flush()
            await rbac.ensure_system_roles_for_product(db, product_id=product.id)
            tenant = Tenant(
                product_id=product.id, name="Test Practice",
                slug=seed_acme.DEV_TENANT_SLUG, is_root=True,
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

        plans = await seed_acme._ensure_plans(db, product.id)
        await seed_acme._ensure_components(db, product.id)
        await seed_acme._ensure_dev_subscription(
            db, product_id=product.id, tenant=tenant,
            plan=plans[seed_acme.DEV_PLAN_CODE],
        )
    return product, tenant, user


# ---------------------------------------------------------------------------
# Catalog spec invariants (the contract, independent of the DB)
# ---------------------------------------------------------------------------

def test_plan_catalog_ai_message_grants() -> None:
    grants = {p["code"]: p["ai_messages"] for p in seed_acme.PLANS}
    assert grants["essentials"] == Decimal("0")
    assert grants["practice"] == Decimal("500")
    assert grants["concierge"] == Decimal("2000")
    assert grants["clinic"] is None  # relies on unlimited_ai component
    # Annual cadences carry the same ai_messages grant as their monthly tier.
    assert grants["essentials_yearly"] == Decimal("0")
    assert grants["practice_yearly"] == Decimal("500")
    assert grants["concierge_yearly"] == Decimal("2000")


def test_plan_catalog_has_monthly_and_annual_cadence_per_paid_tier() -> None:
    """Every paid tier ships a monthly and an annual plan with distinct codes,
    the annual carrying interval=YEAR, trial_days=30, and price = 10× monthly
    ("2 months free"). The site's yearly toggle sends the `_yearly` code."""
    by_code = {p["code"]: p for p in seed_acme.PLANS}
    for tier in ("essentials", "practice", "concierge"):
        monthly = by_code[tier]
        annual = by_code[f"{tier}_yearly"]

        assert monthly["interval"] is BillingInterval.MONTH
        assert annual["interval"] is BillingInterval.YEAR

        # Both cadences run the same 30-day deferred-charge trial.
        assert monthly["trial_days"] == 30
        assert annual["trial_days"] == 30

        # Annual is 10× monthly — "2 months free".
        assert annual["price_cents"] == monthly["price_cents"] * 10

        # Both are public (the site toggle switches between them).
        assert monthly["is_public"] is True
        assert annual["is_public"] is True

        # Each cadence carries its OWN live Razorpay plan_id (a separate annual
        # plan_id encodes the annual billing period). Monthly and annual must
        # point at DIFFERENT plans.
        assert monthly["provider_refs"]["razorpay"].startswith("plan_")
        assert annual["provider_refs"]["razorpay"].startswith("plan_")
        assert monthly["provider_refs"]["razorpay"] != annual["provider_refs"]["razorpay"]


def test_component_plan_gating_spec() -> None:
    gates = {c["code"]: c["required_plan_codes"] for c in seed_acme.COMPONENTS}
    assert set(gates) == {
        "ai_receptionist", "voice_notes", "payment_followups", "weekly_digest",
        "followup_agent", "analytics", "multi_practitioner", "admin_roles",
        "unlimited_ai",
    }
    # The non-public 'beta' plan unlocks every component (all-features access).
    # Each paid tier's ANNUAL cadence (`<tier>_yearly`) is gated identically to
    # its monthly counterpart — a yearly subscriber keeps the same features.
    # Practice-and-up components.
    for code in ("ai_receptionist", "voice_notes", "payment_followups", "weekly_digest"):
        assert gates[code] == [
            "practice", "practice_yearly", "concierge", "concierge_yearly", "clinic", "beta",
        ]
    # Concierge-and-up.
    for code in ("followup_agent", "analytics"):
        assert gates[code] == ["concierge", "concierge_yearly", "clinic", "beta"]
    # Clinic-only (+ beta) — Clinic has no annual cadence (custom-priced).
    for code in ("multi_practitioner", "admin_roles", "unlimited_ai"):
        assert gates[code] == ["clinic", "beta"]


# ---------------------------------------------------------------------------
# End-to-end against a seeded product
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plans_and_components_created() -> None:
    product, _tenant, _user = await _bootstrap_acme_product()
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
    _product, _tenant, user = await _bootstrap_acme_product()
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
    _product, tenant, _user = await _bootstrap_acme_product()
    pid = _product.id
    async with session_scope() as db:
        wallet = await credit_svc._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=pid,
            feature_key=seed_acme.AI_FEATURE_KEY,
        )
        assert wallet.balance == Decimal("500")

    # Consuming an AI message debits the wallet.
    async with session_scope() as db:
        w = await credit_svc.consume(
            db, tenant_id=tenant.id, product_id=pid,
            feature_key=seed_acme.AI_FEATURE_KEY, amount=Decimal("1"),
        )
        assert w.balance == Decimal("499")

    # Overdrawing the quota raises InsufficientCredits (the enforcement gate).
    async with session_scope() as db:
        with pytest.raises(InsufficientCredits):
            await credit_svc.consume(
                db, tenant_id=tenant.id, product_id=pid,
                feature_key=seed_acme.AI_FEATURE_KEY, amount=Decimal("100000"),
            )


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    """Re-running the catalog seed doesn't double-grant credits or duplicate
    components."""
    product, tenant, _user = await _bootstrap_acme_product()
    async with session_scope() as db:
        plans = await seed_acme._ensure_plans(db, product.id)
        await seed_acme._ensure_components(db, product.id)
        await seed_acme._ensure_dev_subscription(
            db, product_id=product.id, tenant=tenant,
            plan=plans[seed_acme.DEV_PLAN_CODE],
        )
    async with session_scope() as db:
        comps = await component_svc.list_components(db, product_id=product.id)
        wallet = await credit_svc._get_or_create_wallet(
            db, tenant_id=tenant.id, product_id=product.id,
            feature_key=seed_acme.AI_FEATURE_KEY,
        )
    assert len(comps) == 9
    assert wallet.balance == Decimal("500")  # not 1000


async def _plans_by_code(product_id) -> dict[str, Plan]:  # type: ignore[no-untyped-def]
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            from sqlalchemy import select

            rows = (
                await db.scalars(select(Plan).where(Plan.product_id == product_id))
            ).all()
    return {p.code: p for p in rows}


@pytest.mark.asyncio
async def test_seed_creates_monthly_and_annual_plan_rows() -> None:
    """The seed persists both cadences per paid tier with the right interval,
    trial_days and 10× annual price in the DB (not just the spec)."""
    product, _tenant, _user = await _bootstrap_acme_product()
    plans = await _plans_by_code(product.id)

    for tier in ("essentials", "practice", "concierge"):
        assert tier in plans
        assert f"{tier}_yearly" in plans
        monthly, annual = plans[tier], plans[f"{tier}_yearly"]
        assert monthly.interval is BillingInterval.MONTH
        assert annual.interval is BillingInterval.YEAR
        assert annual.trial_days == 30
        assert annual.price_cents == monthly.price_cents * 10
        assert annual.is_public is True


@pytest.mark.asyncio
async def test_reseed_applies_seed_razorpay_id_but_preserves_other_providers() -> None:
    """The seed is the source of truth for the `razorpay` plan_id (it now ships
    the real live ids), so a re-seed re-applies it. But a DIFFERENT provider key
    set out-of-band (e.g. a Stripe price) must survive the merge — the seed only
    overwrites the keys it carries, never wipes the whole dict."""
    product, _tenant, _user = await _bootstrap_acme_product()

    from sqlalchemy import select

    # Simulate ops adding a Stripe ref out-of-band, and a stale razorpay id.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            annual = await db.scalar(
                select(Plan).where(
                    Plan.product_id == product.id, Plan.code == "practice_yearly"
                )
            )
            annual.provider_refs = {"razorpay": "plan_STALE", "stripe": "price_KEEP"}

    async with session_scope() as db:
        await seed_acme._ensure_plans(db, product.id)

    plans = await _plans_by_code(product.id)
    refs = plans["practice_yearly"].provider_refs
    # Seed's canonical razorpay id wins over the stale one...
    assert refs["razorpay"] == "plan_TNZwhu3TVqwUBX"
    # ...but the unrelated Stripe key is preserved.
    assert refs["stripe"] == "price_KEEP"


def test_plan_catalog_wa_message_grants() -> None:
    """Every paid tier carries a wa_messages grant (placeholder quotas — see
    TODO(confirm) in seed_acme); yearly matches monthly; unmetered tiers None."""
    grants = {p["code"]: p["wa_messages"] for p in seed_acme.PLANS}
    for tier in ("essentials", "practice", "concierge"):
        assert grants[tier] and grants[tier] > 0
        assert grants[f"{tier}_yearly"] == grants[tier]
    assert grants["clinic"] is None and grants["beta"] is None


@pytest.mark.asyncio
async def test_practice_tenant_gets_wa_messages_wallet_and_can_consume() -> None:
    """Without a wa_messages wallet `credit.consume` raises NotFound — the
    send-metering gap. The seed must create it alongside ai_messages."""
    _product, tenant, _user = await _bootstrap_acme_product()
    expected = next(p for p in seed_acme.PLANS if p["code"] == "practice")["wa_messages"]
    async with session_scope() as db:
        w = await credit_svc.consume(
            db, tenant_id=tenant.id, product_id=_product.id,
            feature_key=seed_acme.WA_FEATURE_KEY, amount=Decimal("1"),
        )
        assert w.balance == expected - 1


@pytest.mark.asyncio
async def test_backfill_grants_wa_wallet_to_preexisting_tenant_once() -> None:
    """A tenant subscribed before the plan carried wa_messages gets the grant
    from the seed backfill — exactly once across re-runs."""
    from sqlalchemy import select

    from app.models.credit import CreditWallet

    product, tenant, _user = await _bootstrap_acme_product()
    # Simulate "predates wa_messages": drop the wallet the seed just created.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            w = await db.scalar(select(CreditWallet).where(
                CreditWallet.tenant_id == tenant.id,
                CreditWallet.feature_key == seed_acme.WA_FEATURE_KEY,
            ))
            if w is not None:
                from app.models.credit import CreditLedger
                for e in (await db.scalars(select(CreditLedger).where(CreditLedger.wallet_id == w.id))).all():
                    await db.delete(e)
                await db.delete(w)
    expected = next(p for p in seed_acme.PLANS if p["code"] == "practice")["wa_messages"]
    for _ in range(2):
        async with session_scope() as db:
            await seed_acme._backfill_wa_wallets(db, product_id=product.id)
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            w = await db.scalar(select(CreditWallet).where(
                CreditWallet.tenant_id == tenant.id,
                CreditWallet.feature_key == seed_acme.WA_FEATURE_KEY,
            ))
            assert w is not None and w.balance == expected
