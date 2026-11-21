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
    `scripts.seed_mayva` seeds for the mayva-practice product (14-day deferred
    trial, empty provider_refs; the mock provider falls back to the plan code).

    Plans live in the session-preserved catalog (not truncated between tests),
    so this is create-if-absent AND marked `is_public=False` to avoid leaking
    into the exact-set assertion in test_plans.py::test_list_plans_public_only.
    `get_by_code` (what checkout uses) resolves regardless of is_public, so the
    cadence/trial path is exercised identically; the real seed plans' public
    flag is asserted in tests/integration/test_mayva_catalog.py."""
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
    # trial (as the mayva-practice Essentials plan does — the producta test
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


@pytest.mark.asyncio
async def test_webhook_reads_razorpay_signature_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Razorpay signs with `X-Razorpay-Signature` (not `Stripe-Signature`).
    The handler must forward whichever header is present to the provider."""
    from app.api.v1 import webhooks as webhooks_mod
    from app.providers.billing.base import WebhookEvent

    seen: list[str] = []

    class _Stub:
        name = "razorpay"

        async def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
            seen.append(signature)
            if signature != "good":
                raise RuntimeError("bad signature")
            return WebhookEvent(id="evt_x", type="noop.event", data={})

    monkeypatch.setattr(webhooks_mod, "get_billing_provider", lambda: _Stub())

    ok = await client.post(
        "/api/v1/webhooks/billing", content=b"{}",
        headers={"X-Razorpay-Signature": "good"},
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/api/v1/webhooks/billing", content=b"{}",
        headers={"X-Razorpay-Signature": "nope"},
    )
    assert bad.status_code == 400
    stripe = await client.post(
        "/api/v1/webhooks/billing", content=b"{}",
        headers={"Stripe-Signature": "good"},
    )
    assert stripe.status_code == 200
    assert seen == ["good", "nope", "good"]


@pytest.mark.asyncio
async def test_expire_lapsed_trials_sweeps_only_lapsed_trials(client: AsyncClient) -> None:
    """TRIAL past `trial_end + buffer` → EXPIRED (access cut) with an audit
    entry; in-window trials and non-TRIAL subscriptions are untouched; a late
    `subscription.charged` webhook revives an expired one."""
    from app.services import subscription as sub_svc

    lapsed = await register_tenant(client, slug="lapsed-co")
    fresh = await register_tenant(client, slug="fresh-co")
    assert lapsed and fresh
    lapsed_sub = await _subscription_for_tenant("lapsed-co")
    fresh_sub = await _subscription_for_tenant("fresh-co")

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.get(Subscription, lapsed_sub.id)
            row.status = SubscriptionStatus.TRIAL
            row.trial_end = datetime.now(UTC) - timedelta(days=5)
            row.provider_subscription_id = "sub_lapsed_1"
            keep = await db.get(Subscription, fresh_sub.id)
            keep.status = SubscriptionStatus.TRIAL
            keep.trial_end = datetime.now(UTC) + timedelta(days=5)

    async with session_scope() as db:
        n = await sub_svc.expire_lapsed_trials(db)
    assert n >= 1

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            assert (await db.get(Subscription, lapsed_sub.id)).status == SubscriptionStatus.EXPIRED
            assert not (await db.get(Subscription, lapsed_sub.id)).has_access
            assert (await db.get(Subscription, fresh_sub.id)).status == SubscriptionStatus.TRIAL

    # Idempotent: a second sweep finds nothing new for these rows.
    async with session_scope() as db:
        assert await sub_svc.expire_lapsed_trials(db) == 0

    # A late first-charge webhook reactivates it.
    payload = json.dumps({
        "id": "evt_late_charge", "type": "subscription.charged",
        "data": {"subscription": {"entity": {"id": "sub_lapsed_1"}}},
    }).encode()
    assert (await client.post("/api/v1/webhooks/billing", content=payload)).status_code == 200
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            assert (await db.get(Subscription, lapsed_sub.id)).status == SubscriptionStatus.ACTIVE


async def _checkout_sub(client: AsyncClient, slug: str) -> tuple[Subscription, str]:
    tok = await register_tenant(client, slug=slug)
    await client.post(
        "/api/v1/billing/checkout", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    sub = await _subscription_for_tenant(slug)
    assert sub.provider_subscription_id
    return sub, tok["access_token"]


async def _fire(client: AsyncClient, event: str, provider_sub_id: str) -> None:
    payload = json.dumps({
        "id": f"evt_{event}", "type": event,
        "data": {"subscription": {"entity": {"id": provider_sub_id}}},
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200


async def _status(sub_id) -> SubscriptionStatus:  # noqa: ANN001
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            return (await db.get(Subscription, sub_id)).status


@pytest.mark.asyncio
async def test_webhook_authenticated_records_mandate_without_activating(client: AsyncClient) -> None:
    sub, access = await _checkout_sub(client, "mandate-co")
    before = await client.get("/api/v1/subscription", headers=auth(access))
    assert before.json()["mandate_authorized"] is False

    await _fire(client, "subscription.authenticated", sub.provider_subscription_id)

    after = await client.get("/api/v1/subscription", headers=auth(access))
    assert after.json()["mandate_authorized"] is True
    assert after.json()["status"] == "trial"  # label stays TRIAL until first charge


@pytest.mark.asyncio
async def test_webhook_pending_halted_cancelled_drive_status(client: AsyncClient) -> None:
    sub, _ = await _checkout_sub(client, "lifecycle-co")
    pid = sub.provider_subscription_id

    await _fire(client, "subscription.pending", pid)
    assert await _status(sub.id) == SubscriptionStatus.PAST_DUE

    await _fire(client, "subscription.halted", pid)
    assert await _status(sub.id) == SubscriptionStatus.GRACE

    await _fire(client, "subscription.cancelled", pid)
    assert await _status(sub.id) == SubscriptionStatus.CANCELLED
    await _fire(client, "subscription.cancelled", pid)  # idempotent
    assert await _status(sub.id) == SubscriptionStatus.CANCELLED

    # A late/out-of-order charge must NOT resurrect a cancelled subscription.
    await _fire(client, "subscription.charged", pid)
    assert await _status(sub.id) == SubscriptionStatus.CANCELLED
