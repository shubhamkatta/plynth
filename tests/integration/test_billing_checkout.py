"""Marketing-site billing checkout (POST /billing/checkout) + Razorpay
subscription-lifecycle webhook. Driven by the mock billing provider, whose
`create_subscription` returns a fake hosted `short_url` (the redirect URL)."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.subscription import Subscription, SubscriptionStatus
from tests.conftest import auth, register_tenant


async def _subscription_for_tenant(slug: str) -> Subscription:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            return await db.scalar(
                select(Subscription).where(Subscription.tenant.has(slug=slug))
            )


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
