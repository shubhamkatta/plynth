"""Seed the Mayva product's plan catalog + component entitlements + AI
credit grants, and put the dev/demo tenant on the Practice plan.

Mayva (product slug ``mayva``) is the AI practice assistant for
therapists/counsellors. This script defines the tier catalog the Mayva
app reads via:

- ``GET /auth/me``      → ``components`` map (entitlement code → access)
- ``GET /subscription`` → ``plan_code`` (the tenant's tier)
- ``GET /credits/wallets`` → the ``ai_messages`` quota wallet

Idempotent: re-runs are safe. Requires the ``mayva`` product to already
exist (created via ``POST /admin/products`` with slug ``mayva``).

Run against the running stack:

    docker compose exec api python -m scripts.seed_mayva
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.core.tenant import (
    bypass_product,
    bypass_tenant,
    set_current_product,
    set_current_tenant,
)
from app.models.credit import CreditWallet
from app.models.plan import BillingInterval, Plan, PlanFeature
from app.models.product import Product, ProductStatus
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.tenant import Tenant
from app.services import component as component_svc
from app.services import credit as credit_svc
from app.services import plan as plan_svc
from app.services import rbac

log = get_logger("seed_mayva")

PRODUCT_SLUG = "mayva-practice"

# The dev/demo tenant that Mayva's gate0 / DEV tenant maps to.
DEV_TENANT_SLUG = "test-practice"
DEV_PLAN_CODE = "practice"

# AI-message quota is metered as credits under this feature_key. Mayva
# consumes 1 per outbound AI message; it SKIPS consumption entirely when
# the `unlimited_ai` component is active (Clinic tier).
AI_FEATURE_KEY = "ai_messages"

# --------------------------------------------------------------------------
# Plan catalog. Prices are per-region on the marketing site; plynth stores a
# single default (USD cents). Per-region plan variants are NOT modelled here
# (see the flag in the handoff report).
# --------------------------------------------------------------------------
PLANS: list[dict] = [
    {
        "code": "essentials",
        "name": "Essentials",
        "description": "Booking + typed notes. The baseline front desk.",
        "price_cents": 2900,
        "trial_days": 14,
        "is_public": True,
        # No AI on Essentials — 0 documents the intent (no wallet is created).
        "ai_messages": Decimal("0"),
    },
    {
        "code": "practice",
        "name": "Practice",
        "description": "AI receptionist, voice notes, payment follow-ups, weekly digest.",
        "price_cents": 7900,
        "trial_days": 14,
        "is_public": True,
        "ai_messages": Decimal("500"),
    },
    {
        "code": "concierge",
        "name": "Concierge",
        "description": "Everything in Practice plus the follow-up agent and analytics.",
        "price_cents": 19900,
        "trial_days": 14,
        "is_public": True,
        "ai_messages": Decimal("2000"),
    },
    {
        "code": "clinic",
        "name": "Clinic",
        "description": "Multi-practitioner clinic tier with admin roles and unlimited AI. Custom pricing.",
        "price_cents": 0,          # custom / enterprise — priced per deal
        "trial_days": 0,
        "is_public": False,        # not shown in the public /plans list
        # No ai_messages grant — Clinic relies on the `unlimited_ai`
        # component and Mayva skips credit consumption entirely.
        "ai_messages": None,
    },
    {
        "code": "beta",
        "name": "Beta (all features)",
        "description": "Early-access / internal beta — every feature enabled, unlimited AI.",
        "price_cents": 0,
        "trial_days": 0,
        "is_public": False,        # not shown in the public /plans list
        # Unlimited AI via the `unlimited_ai` component (below) — no quota.
        "ai_messages": None,
    },
]

# --------------------------------------------------------------------------
# Component entitlements. `required_plan_codes` gates each one: a tenant
# whose active plan is NOT in the list gets is_enabled=False (source="plan")
# in /auth/me. Essentials qualifies for none (booking + typed notes are the
# ungated baseline, not components).
# --------------------------------------------------------------------------
# "beta" is included in every gate so the Beta plan unlocks ALL components
# (including unlimited_ai → no AI-message quota). Early-access / internal tier.
_PRACTICE_UP = ["practice", "concierge", "clinic", "beta"]
_CONCIERGE_UP = ["concierge", "clinic", "beta"]
_CLINIC_ONLY = ["clinic", "beta"]

COMPONENTS: list[dict] = [
    {"code": "ai_receptionist", "name": "AI Receptionist",
     "description": "AI front desk: triage, drafts, reminders.", "required_plan_codes": _PRACTICE_UP},
    {"code": "voice_notes", "name": "Voice Notes",
     "description": "Dictated / transcribed session notes.", "required_plan_codes": _PRACTICE_UP},
    {"code": "payment_followups", "name": "Payment Follow-ups",
     "description": "Automated payment links + nudges.", "required_plan_codes": _PRACTICE_UP},
    {"code": "weekly_digest", "name": "Weekly Digest",
     "description": "Weekly practice digest.", "required_plan_codes": _PRACTICE_UP},
    {"code": "followup_agent", "name": "Follow-up Agent",
     "description": "Proactive client follow-up scheduling agent.", "required_plan_codes": _CONCIERGE_UP},
    {"code": "analytics", "name": "Analytics",
     "description": "Practice analytics + reporting.", "required_plan_codes": _CONCIERGE_UP},
    {"code": "multi_practitioner", "name": "Multi-practitioner",
     "description": "Multiple practitioners under one clinic.", "required_plan_codes": _CLINIC_ONLY},
    {"code": "admin_roles", "name": "Admin Roles",
     "description": "Clinic admin / front-desk role management.", "required_plan_codes": _CLINIC_ONLY},
    {"code": "unlimited_ai", "name": "Unlimited AI",
     "description": "Unmetered AI messages (bypasses the ai_messages quota).",
     "required_plan_codes": _CLINIC_ONLY},
]

CATALOG_PLAN_CODES = {p["code"] for p in PLANS}


async def _ensure_plans(db: AsyncSession, product_id: UUID) -> dict[str, Plan]:
    """Create/refresh the 4 catalog plans + their ai_messages PlanFeature.
    Idempotent. Also deactivates any legacy non-catalog plans so /plans
    only surfaces the real Mayva tiers."""
    by_code: dict[str, Plan] = {}
    with bypass_product(), bypass_tenant():
        existing = {
            p.code: p
            for p in (
                await db.scalars(select(Plan).where(Plan.product_id == product_id))
            ).all()
        }
        for spec in PLANS:
            plan = existing.get(spec["code"])
            if plan is None:
                plan = Plan(
                    product_id=product_id,
                    code=spec["code"],
                    name=spec["name"],
                    description=spec["description"],
                    price_cents=spec["price_cents"],
                    currency="USD",
                    interval=BillingInterval.MONTH,
                    trial_days=spec["trial_days"],
                    is_public=spec["is_public"],
                    is_active=True,
                )
                db.add(plan)
                await db.flush()
                log.info("seed_mayva.plan_created", code=plan.code)
            else:
                plan.name = spec["name"]
                plan.description = spec["description"]
                plan.price_cents = spec["price_cents"]
                plan.trial_days = spec["trial_days"]
                plan.is_public = spec["is_public"]
                plan.is_active = True
            by_code[plan.code] = plan

            # Ensure the ai_messages PlanFeature carries the right grant.
            if spec["ai_messages"] is not None:
                feat = await db.scalar(
                    select(PlanFeature).where(
                        PlanFeature.plan_id == plan.id,
                        PlanFeature.feature_key == AI_FEATURE_KEY,
                    )
                )
                if feat is None:
                    db.add(PlanFeature(
                        product_id=product_id, plan_id=plan.id,
                        feature_key=AI_FEATURE_KEY,
                        limit_value=None, credit_amount=spec["ai_messages"],
                    ))
                else:
                    feat.credit_amount = spec["ai_messages"]

        # Additive only — legacy plans (free/pro/enterprise/…) are intentionally
        # LEFT UNTOUCHED. The 'mayva' product slug is shared with an earlier
        # product version whose users still hold active legacy-plan subscriptions
        # (e.g. free); deactivating those plans out from under a live subscriber
        # would break their access. New catalog plans are simply added alongside.
        await db.flush()
    return by_code


async def _ensure_components(db: AsyncSession, product_id: UUID) -> None:
    """Create the 9 entitlement components with plan gating. Idempotent —
    updates required_plan_codes on re-run."""
    existing = {
        c.code: c
        for c in await component_svc.list_components(
            db, product_id=product_id, include_inactive=True
        )
    }
    for spec in COMPONENTS:
        if spec["code"] in existing:
            await component_svc.update_component(
                db, product_id=product_id, code=spec["code"],
                changes={
                    "name": spec["name"],
                    "description": spec["description"],
                    "required_plan_codes": spec["required_plan_codes"],
                    "is_active": True,
                    "is_default_enabled": True,
                },
            )
        else:
            await component_svc.create_component(
                db, product_id=product_id,
                code=spec["code"], name=spec["name"],
                description=spec["description"],
                required_plan_codes=spec["required_plan_codes"],
            )
            log.info("seed_mayva.component_created", code=spec["code"])


async def _ensure_dev_subscription(
    db: AsyncSession, *, product_id: UUID, tenant: Tenant, plan: Plan,
) -> Subscription:
    """Put the dev tenant on an ACTIVE subscription for `plan` and grant its
    plan credits (the ai_messages quota). Idempotent."""
    now = datetime.now(UTC)
    with bypass_product(), bypass_tenant():
        sub = await db.scalar(
            select(Subscription).where(Subscription.tenant_id == tenant.id)
        )
        if sub is None:
            sub = Subscription(
                product_id=product_id, tenant_id=tenant.id, plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
                trial_end=None, provider="mock",
            )
            db.add(sub)
            log.info("seed_mayva.subscription_created", tenant=tenant.slug, plan=plan.code)
        else:
            sub.plan_id = plan.id
            sub.status = SubscriptionStatus.ACTIVE
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=30)
            sub.trial_end = None
            sub.cancel_at_period_end = False
            sub.cancelled_at = None
            log.info("seed_mayva.subscription_updated", tenant=tenant.slug, plan=plan.code)
        await db.flush()

    # Grant the plan's credit allotments (ai_messages: 500 for Practice).
    # Re-load with features eager so grant_plan_credits doesn't lazy-load.
    # Stable reference → re-runs don't double-grant.
    plan_with_features = await plan_svc.get_by_code(
        db, product_id=product_id, code=plan.code
    )
    await credit_svc.grant_plan_credits(
        db, tenant_id=tenant.id, product_id=product_id, plan=plan_with_features,
        reference=f"seed:{sub.id}:{plan.code}",
    )

    # Bind the ai_messages wallet to the current period for realism.
    with bypass_product(), bypass_tenant():
        wallet = await db.scalar(
            select(CreditWallet).where(
                CreditWallet.tenant_id == tenant.id,
                CreditWallet.feature_key == AI_FEATURE_KEY,
            )
        )
        if wallet is not None and wallet.period_start is None:
            wallet.period_start = now
            wallet.period_end = now + timedelta(days=30)
            await db.flush()
    return sub


async def main() -> None:
    configure_logging()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                select(Product).where(Product.slug == PRODUCT_SLUG)
            )
            if product is None:
                # Self-contained bootstrap: the mayva-practice product is the
                # therapist front-desk product, kept SEPARATE from the legacy
                # 'mayva' product (whose old users must stay intact). Create it
                # + its system roles here so this seed sets up a greenfield
                # environment (local or prod) in one run.
                product = Product(
                    name="Mayva Practice",
                    slug=PRODUCT_SLUG,
                    status=ProductStatus.ACTIVE,
                    is_active=True,
                )
                db.add(product)
                await db.flush()
                await rbac.ensure_system_roles_for_product(db, product_id=product.id)
                log.info("seed_mayva.product_created", slug=PRODUCT_SLUG)
            tenant = await db.scalar(
                select(Tenant).where(
                    Tenant.product_id == product.id, Tenant.slug == DEV_TENANT_SLUG
                )
            )

        set_current_product(product.id)
        if tenant is not None:
            set_current_tenant(tenant.id)

        plans = await _ensure_plans(db, product.id)
        await _ensure_components(db, product.id)

        if tenant is None:
            log.warning(
                "seed_mayva.dev_tenant_missing", slug=DEV_TENANT_SLUG,
                note="plans + components seeded; skipped subscription seeding",
            )
        else:
            await _ensure_dev_subscription(
                db, product_id=product.id, tenant=tenant, plan=plans[DEV_PLAN_CODE],
            )
    log.info("seed_mayva.done")


if __name__ == "__main__":
    asyncio.run(main())
