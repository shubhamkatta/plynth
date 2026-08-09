"""Marketing-site billing checkout (POST /billing/checkout) + Razorpay
subscription-lifecycle webhook. Driven by the mock billing provider, whose
`create_subscription` returns a fake hosted `short_url` (the redirect URL)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.plan import BillingInterval, Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.providers.billing import get_billing_provider
from tests.conftest import auth, product_id, register_tenant


async def _subscription_for_tenant(slug: str) -> Subscription:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            return await db.scalar(
                select(Subscription).where(Subscription.tenant.has(slug=slug))
            )


async def _ensure_annual_plan(
    *, code: str = "practice_yearly", price_cents: int = 79000
) -> None:
    """Idempotently add an ANNUAL (interval=YEAR) plan to the `producta` test
    product so checkout can resolve a yearly plan_code — mirrors what
    `scripts.seed_acme` seeds for the acme-practice product (14-day deferred
    trial, empty provider_refs; the mock provider falls back to the plan code).

    Plans live in the session-preserved catalog (not truncated between tests),
    so this is create-if-absent AND marked `is_public=False` to avoid leaking
    into the exact-set assertion in test_plans.py::test_list_plans_public_only.
    `get_by_code` (what checkout uses) resolves regardless of is_public, so the
    cadence/trial path is exercised identically; the real seed plans' public
    flag is asserted in tests/integration/test_acme_catalog.py."""
    pid = product_id("producta")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            existing = await db.scalar(
                select(Plan).where(Plan.product_id == pid, Plan.code == code)
            )
            if existing is None:
                db.add(Plan(
                    product_id=pid, code=code, name="Practice (Annual)",
                    price_cents=price_cents, interval=BillingInterval.YEAR,
                    trial_days=14, is_public=False, provider_refs={},
                ))


@pytest.mark.asyncio
async def test_checkout_paid_plan_returns_redirect_url(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Mock provider stands in for Razorpay's short_url.
    assert body["url"] is not None
    assert body["url"].startswith("https://mock-billing.local/checkout/")
    assert body["subscription_id"] is not None

    # The subscription is now linked to the provider subscription id.
    sub = await _subscription_for_tenant("acme")
    assert sub.provider_subscription_id == body["subscription_id"]


@pytest.mark.asyncio
async def test_checkout_paid_plan_defers_first_charge_to_trial_end(
    client: AsyncClient,
) -> None:
    """Paid checkout must create the provider subscription with a NON-zero trial
    (14 days) so the mandate is authorized now but the first charge is deferred
    to trial end — not charged immediately on authorization (the PR #69 bug was
    trial_days hardcoded to 0)."""
    tok = await register_tenant(client, slug="acme")
    before = datetime.now(UTC)
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},  # 14-day trial in the seed template
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text

    sub = await _subscription_for_tenant("acme")
    # Local subscription is on trial (NOT active) with access and a ~14d trial.
    assert sub.status == SubscriptionStatus.TRIAL
    assert sub.has_access is True
    assert sub.trial_end is not None
    assert timedelta(days=13) < (sub.trial_end - before) < timedelta(days=15)

    # The provider was called with trial_days == 14 (not 0), and the returned
    # subscription defers its first billing period (start_at) ~14 days out.
    provider = get_billing_provider()
    p_sub = provider._subscriptions[sub.provider_subscription_id]  # type: ignore[attr-defined]
    assert p_sub.trial_days == 14
    assert timedelta(days=13) < (p_sub.current_period_start - before) < timedelta(days=15)


@pytest.mark.asyncio
async def test_checkout_annual_plan_resolves_and_defers_first_charge(
    client: AsyncClient,
) -> None:
    """Checkout on an ANNUAL plan_code (`practice_yearly`) resolves the annual
    plan and creates a provider subscription that defers the first charge ~14
    days — same card-on-file trial as monthly, just billed yearly thereafter.
    The annual cadence is carried by the resolved plan (interval=YEAR); the
    trial deferral logic is cadence-agnostic."""
    await _ensure_annual_plan()
    tok = await register_tenant(client, slug="acme")
    before = datetime.now(UTC)
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "practice_yearly"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] is not None
    assert body["subscription_id"] is not None

    sub = await _subscription_for_tenant("acme")
    # Resolved the ANNUAL plan (interval=YEAR) with the annual price.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            plan = await db.get(Plan, sub.plan_id)
    assert plan.code == "practice_yearly"
    assert plan.interval is BillingInterval.YEAR
    assert plan.price_cents == 79000

    # On trial with access; first charge deferred ~14 days (mandate now).
    assert sub.status == SubscriptionStatus.TRIAL
    assert sub.has_access is True
    assert sub.trial_end is not None
    assert timedelta(days=13) < (sub.trial_end - before) < timedelta(days=15)

    provider = get_billing_provider()
    p_sub = provider._subscriptions[sub.provider_subscription_id]  # type: ignore[attr-defined]
    assert p_sub.trial_days == 14
    assert timedelta(days=13) < (p_sub.current_period_start - before) < timedelta(days=15)


@pytest.mark.asyncio
async def test_register_then_checkout_is_one_trial_not_stacked(
    client: AsyncClient,
) -> None:
    """register→checkout must yield ONE trial, charged once after it — not two
    stacked trials. When a local trial is already running, checkout defers the
    first Razorpay charge to that EXISTING trial_end rather than opening a
    fresh 14-day trial on top of it."""
    tok = await register_tenant(client, slug="acme")

    # Simulate register→start_trial having put the tenant on a mid-flight local
    # trial (as the acme-practice Essentials plan does — the producta test
    # product's cheapest plan is $0 so it activates instead). 10 days remain.
    existing_trial_end = datetime.now(UTC) + timedelta(days=10)
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.scalar(select(Subscription).where(Subscription.tenant.has(slug="acme")))
            row.status = SubscriptionStatus.TRIAL
            row.trial_end = existing_trial_end

    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text

    sub = await _subscription_for_tenant("acme")
    assert sub.status == SubscriptionStatus.TRIAL
    # trial_end is PRESERVED (~10d), NOT pushed out to now+14d → no double trial.
    assert abs((sub.trial_end - existing_trial_end).total_seconds()) < 5
    assert sub.trial_end < datetime.now(UTC) + timedelta(days=12)

    # The provider charge is deferred to the SAME (remaining ~10d) trial end,
    # so the single trial ends in one charge — it is not 14 + 10 = 24 days out.
    provider = get_billing_provider()
    p_sub = provider._subscriptions[sub.provider_subscription_id]  # type: ignore[attr-defined]
    assert 9 <= p_sub.trial_days <= 10
    assert p_sub.current_period_start < datetime.now(UTC) + timedelta(days=12)


@pytest.mark.asyncio
async def test_checkout_free_plan_activates_without_redirect(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "free"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] is None
    assert body["status"] == "active"

    # Free plan never mints a provider subscription.
    sub = await _subscription_for_tenant("acme")
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.provider_subscription_id is None


@pytest.mark.asyncio
async def test_checkout_requires_authentication(client: AsyncClient) -> None:
    # No JWT → 401 before the permission check even runs.
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},
        headers={"X-Product-Slug": "producta"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_checkout_unknown_plan_404s(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "no-such-plan"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_subscription_activated_marks_active(client: AsyncClient) -> None:
    """A Razorpay-shaped `subscription.activated` event flips a non-active
    subscription back to ACTIVE. The provider subscription id is read from the
    nested `payload.subscription.entity.id`."""
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    sub = await _subscription_for_tenant("acme")
    provider_sub_id = sub.provider_subscription_id
    assert provider_sub_id is not None

    # Drive it out of ACTIVE first so activation is observable.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.get(Subscription, sub.id)
            row.status = SubscriptionStatus.PAST_DUE

    payload = json.dumps({
        "id": "evt_sub_act_1",
        "type": "subscription.activated",
        "data": {"subscription": {"entity": {"id": provider_sub_id}}},
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200
    assert r.json()["received"] == "true"

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            updated = await db.get(Subscription, sub.id)
            assert updated.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_webhook_subscription_activated_unknown_returns_200(client: AsyncClient) -> None:
    payload = json.dumps({
        "id": "evt_sub_act_unknown",
        "type": "subscription.charged",
        "data": {"subscription": {"entity": {"id": "sub_does_not_exist"}}},
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200
