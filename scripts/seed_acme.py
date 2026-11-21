"""Seed the Acme product's plan catalog + component entitlements + AI
credit grants, and put the dev/demo tenant on the Practice plan.

Acme (product slug ``acme``) is the AI practice assistant for
therapists/counsellors. This script defines the tier catalog the Acme
app reads via:

- ``GET /auth/me``      → ``components`` map (entitlement code → access)
- ``GET /subscription`` → ``plan_code`` (the tenant's tier)
- ``GET /credits/wallets`` → the ``ai_messages`` quota wallet

Idempotent: re-runs are safe. Requires the ``acme`` product to already
exist (created via ``POST /admin/products`` with slug ``acme``).

Run against the running stack:

    docker compose exec api python -m scripts.seed_acme
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

log = get_logger("seed_acme")

PRODUCT_SLUG = "acme-practice"

# The dev/demo tenant that Acme's gate0 / DEV tenant maps to.
DEV_TENANT_SLUG = "test-practice"
DEV_PLAN_CODE = "practice"

# AI-message quota is metered as credits under this feature_key. Acme
# consumes 1 per outbound AI message; it SKIPS consumption entirely when
# the `unlimited_ai` component is active (Clinic tier).
AI_FEATURE_KEY = "ai_messages"

# WhatsApp outbound sends are metered under this feature_key (1 credit per
# message the therapist sends from the inbox). Acme calls
# `POST /credits/service/consume` against this wallet; without a wallet the
# consume 404s (`credit._lock_wallet`), so every plan that can send WhatsApp
# must grant it (see `_ensure_plans` + `_backfill_wa_wallets`).
WA_FEATURE_KEY = "wa_messages"

# --------------------------------------------------------------------------
# Plan catalog. Prices are per-region on the marketing site; plynth stores a
# single default (USD cents). Per-region plan variants are NOT modelled here
# (see the flag in the handoff report).
#
# Cadences (monthly + annual)
# ---------------------------
# Each paid tier ships in TWO cadences the marketing site's monthly/yearly
# toggle switches between, distinguished by DISTINCT plan codes:
#
#   monthly → `essentials` / `practice` / `concierge`   (interval=MONTH)
#   annual  → `<tier>_yearly`                            (interval=YEAR)
#
# The annual price is 10× the monthly (`price_cents`), i.e. "2 months free".
# `POST /billing/checkout {plan_code}` resolves either cadence by code; the
# provider (Razorpay) subscription's billing period is carried by the
# provider PLAN itself (annual plan_id ⇒ annual billing), NOT by our
# `interval` column — `interval` is catalog metadata for display/reporting.
# So the annual cadence hinges on `provider_refs["razorpay"]` pointing at an
# ANNUAL Razorpay plan_id (see TODO(billing) below).
#
# Paid plans run a 30-day card-on-file / UPI-AutoPay-mandate free trial (both
# cadences): `trial_days=30` means the customer authorizes a recurring mandate
# at checkout, is NOT charged during the trial, and the first deduction lands
# after 30 days — then recurs monthly OR yearly per the plan's interval
# (see app/services/subscription.py::purchase; the deferral is cadence-agnostic).
#
# TODO(billing): `provider_refs` maps a provider name → its plan id (Razorpay
# `plan_id`). It MUST be populated with the real Razorpay plan_ids created in
# the Razorpay dashboard before checkout works against the live provider —
# `subscription.purchase` raises ValidationFailed for a paid plan with no
# razorpay ref. It is intentionally left EMPTY here: do NOT invent fake
# plan_ids (Razorpay rejects an unknown plan_id at subscription create). Fill
# each paid plan's ref in below, e.g. "provider_refs": {"razorpay": "plan_XXX"}.
# The MONTHLY plans need a monthly Razorpay plan_id; the `_yearly` plans need a
# separate ANNUAL Razorpay plan_id (the plan_id is what encodes the period).
# The mock/dev provider ignores provider_refs (falls back to the plan code).
# --------------------------------------------------------------------------
PLANS: list[dict] = [
    {
        "code": "essentials",
        "name": "Essentials",
        "description": "Booking + typed notes. The baseline front desk.",
        "price_cents": 2900,
        "interval": BillingInterval.MONTH,
        "trial_days": 30,
        "is_public": True,
        # No AI on Essentials — 0 documents the intent (no wallet is created).
        "ai_messages": Decimal("0"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("200"),
        "provider_refs": {"razorpay": "plan_TNZwgF5fQwPTPO"},  # live monthly
    },
    {
        "code": "essentials_yearly",
        "name": "Essentials (Annual)",
        "description": "Booking + typed notes. The baseline front desk. Billed yearly (2 months free).",
        "price_cents": 29000,      # 10× monthly — "2 months free"
        "interval": BillingInterval.YEAR,
        "trial_days": 30,
        "is_public": True,
        "ai_messages": Decimal("0"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("200"),
        "provider_refs": {"razorpay": "plan_TNZwhTa4K96xZF"},  # live annual
    },
    {
        "code": "practice",
        "name": "Practice",
        "description": "AI receptionist, voice notes, payment follow-ups, weekly digest.",
        "price_cents": 7900,
        "interval": BillingInterval.MONTH,
        "trial_days": 30,
        "is_public": True,
        "ai_messages": Decimal("500"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("1000"),
        "provider_refs": {"razorpay": "plan_TNZwgi92BT1iCQ"},  # live monthly
    },
    {
        "code": "practice_yearly",
        "name": "Practice (Annual)",
        "description": "AI receptionist, voice notes, payment follow-ups, weekly digest. Billed yearly (2 mo free).",
        "price_cents": 79000,      # 10× monthly — "2 months free"
        "interval": BillingInterval.YEAR,
        "trial_days": 30,
        "is_public": True,
        "ai_messages": Decimal("500"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("1000"),
        "provider_refs": {"razorpay": "plan_TNZwhu3TVqwUBX"},  # live annual
    },
    {
        "code": "concierge",
        "name": "Concierge",
        "description": "Everything in Practice plus the follow-up agent and analytics.",
        "price_cents": 19900,
        "interval": BillingInterval.MONTH,
        "trial_days": 30,
        "is_public": True,
        "ai_messages": Decimal("2000"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("3000"),
        "provider_refs": {"razorpay": "plan_TNZwh4slGhczxl"},  # live monthly
    },
    {
        "code": "concierge_yearly",
        "name": "Concierge (Annual)",
        "description": "Everything in Practice plus the follow-up agent and analytics. Billed yearly (2 months free).",
        "price_cents": 199000,     # 10× monthly — "2 months free"
        "interval": BillingInterval.YEAR,
        "trial_days": 30,
        "is_public": True,
        "ai_messages": Decimal("2000"),
        # TODO(confirm): placeholder quota — set to the real WhatsApp allowance.
        "wa_messages": Decimal("3000"),
        "provider_refs": {"razorpay": "plan_TNZwiM5Lygue7N"},  # live annual
    },
    {
        "code": "clinic",
        "name": "Clinic",
        "description": "Multi-practitioner clinic tier with admin roles and unlimited AI. Custom pricing.",
        "price_cents": 0,          # custom / enterprise — priced per deal
        "interval": BillingInterval.MONTH,
        "trial_days": 0,
        "is_public": False,        # not shown in the public /plans list
        # No ai_messages grant — Clinic relies on the `unlimited_ai`
        # component and Acme skips credit consumption entirely.
        "ai_messages": None,
        "wa_messages": None,  # unmetered tier: no wallet granted
    },
    {
        "code": "beta",
        "name": "Beta (all features)",
        "description": "Early-access / internal beta — every feature enabled, unlimited AI.",
        "price_cents": 0,
        "interval": BillingInterval.MONTH,
        "trial_days": 0,
        "is_public": False,        # not shown in the public /plans list
        # Unlimited AI via the `unlimited_ai` component (below) — no quota.
        "ai_messages": None,
        "wa_messages": None,  # unmetered tier: no wallet granted
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
#
# Each paid tier's ANNUAL cadence (`<tier>_yearly`) grants the SAME components
# as its monthly counterpart — a yearly subscriber must not lose features for
# paying up front. So every gate that lists a monthly tier also lists its
# `_yearly` code. (Clinic has no annual cadence — it's custom-priced.)
_PRACTICE_UP = [
    "practice", "practice_yearly",
    "concierge", "concierge_yearly",
    "clinic", "beta",
]
_CONCIERGE_UP = ["concierge", "concierge_yearly", "clinic", "beta"]
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
    """Create/refresh the catalog plans (monthly + annual cadences) + their
    ai_messages PlanFeature. Idempotent. Each spec carries its own `interval`
    (MONTH for monthly tiers, YEAR for the `_yearly` cadence)."""
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
                    interval=spec["interval"],
                    trial_days=spec["trial_days"],
                    is_public=spec["is_public"],
                    is_active=True,
                    provider_refs=dict(spec.get("provider_refs") or {}),
                )
                db.add(plan)
                await db.flush()
                log.info("seed_acme.plan_created", code=plan.code)
            else:
                plan.name = spec["name"]
                plan.description = spec["description"]
                plan.price_cents = spec["price_cents"]
                plan.interval = spec["interval"]
                plan.trial_days = spec["trial_days"]
                plan.is_public = spec["is_public"]
                plan.is_active = True
                # Merge in any provider_refs the seed now carries, but NEVER
                # clobber refs already set (out-of-band or a prior seed) with an
                # empty placeholder — an empty {} here means "not yet known".
                if spec.get("provider_refs"):
                    plan.provider_refs = {**plan.provider_refs, **spec["provider_refs"]}
            by_code[plan.code] = plan

            # Ensure each metered PlanFeature (ai_messages, wa_messages)
            # carries the right grant. A None spec value = unmetered/no grant.
            for feature_key in (AI_FEATURE_KEY, WA_FEATURE_KEY):
                grant = spec.get(feature_key)
                if grant is None:
                    continue
                feat = await db.scalar(
                    select(PlanFeature).where(
                        PlanFeature.plan_id == plan.id,
                        PlanFeature.feature_key == feature_key,
                    )
                )
                if feat is None:
                    db.add(PlanFeature(
                        product_id=product_id, plan_id=plan.id,
                        feature_key=feature_key,
                        limit_value=None, credit_amount=grant,
                    ))
                else:
                    feat.credit_amount = grant

        # Additive only — legacy plans (free/pro/enterprise/…) are intentionally
        # LEFT UNTOUCHED. The 'acme' product slug is shared with an earlier
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
            log.info("seed_acme.component_created", code=spec["code"])


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
            log.info("seed_acme.subscription_created", tenant=tenant.slug, plan=plan.code)
        else:
            sub.plan_id = plan.id
            sub.status = SubscriptionStatus.ACTIVE
            sub.current_period_start = now
            sub.current_period_end = now + timedelta(days=30)
            sub.trial_end = None
            sub.cancel_at_period_end = False
            sub.cancelled_at = None
            log.info("seed_acme.subscription_updated", tenant=tenant.slug, plan=plan.code)
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


async def _backfill_wa_wallets(db: AsyncSession, *, product_id: UUID) -> int:
    """Grant the `wa_messages` allotment to tenants that subscribed BEFORE the
    plan carried it. Plan credits otherwise only grant on trial start /
    purchase / plan change / renewal, so existing tenants would have no wallet
    and Acme's send-metering would 404. Idempotent: the reference is stable
    per (subscription, plan), so re-runs never double-grant. Returns the number
    of subscriptions examined."""
    n = 0
    with bypass_product(), bypass_tenant():
        subs = (
            await db.scalars(
                select(Subscription).where(Subscription.product_id == product_id)
            )
        ).all()
        for sub in subs:
            if not sub.has_access:
                continue
            plan = await db.scalar(
                select(Plan)
                .options(selectinload(Plan.features))
                .where(Plan.id == sub.plan_id)
            )
            if plan is None:
                continue
            feat = next(
                (f for f in plan.features if f.feature_key == WA_FEATURE_KEY), None
            )
            if feat is None or not feat.credit_amount or feat.credit_amount <= 0:
                continue
            await credit_svc.grant(
                db, tenant_id=sub.tenant_id, product_id=product_id,
                feature_key=WA_FEATURE_KEY, amount=Decimal(feat.credit_amount),
                reason=f"plan:{plan.code}",
                reference=f"backfill:{sub.id}:{plan.code}:{WA_FEATURE_KEY}",
            )
            n += 1
    return n


async def main() -> None:
    configure_logging()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                select(Product).where(Product.slug == PRODUCT_SLUG)
            )
            if product is None:
                # Self-contained bootstrap: the acme-practice product is the
                # therapist front-desk product, kept SEPARATE from the legacy
                # 'acme' product (whose old users must stay intact). Create it
                # so this seed sets up a greenfield environment in one run.
                product = Product(
                    name="Acme Practice",
                    slug=PRODUCT_SLUG,
                    status=ProductStatus.ACTIVE,
                    is_active=True,
                )
                db.add(product)
                await db.flush()
                log.info("seed_acme.product_created", slug=PRODUCT_SLUG)
            # ALWAYS (idempotently) ensure system roles — not only on first
            # creation. Re-running this seed against an ALREADY-EXISTING product
            # is how newly-added roles (e.g. 'patient') reach production.
            await rbac.ensure_system_roles_for_product(db, product_id=product.id)
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
        backfilled = await _backfill_wa_wallets(db, product_id=product.id)
        log.info("seed_acme.wa_backfill", subscriptions=backfilled)

        if tenant is None:
            log.warning(
                "seed_acme.dev_tenant_missing", slug=DEV_TENANT_SLUG,
                note="plans + components seeded; skipped subscription seeding",
            )
        else:
            await _ensure_dev_subscription(
                db, product_id=product.id, tenant=tenant, plan=plans[DEV_PLAN_CODE],
            )
    log.info("seed_acme.done")


if __name__ == "__main__":
    asyncio.run(main())
