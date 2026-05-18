"""Billing webhook (mock provider). Stripe is not exercised here."""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_tenant
from app.models.subscription import Subscription, SubscriptionStatus
from tests.conftest import auth, register_tenant


async def _subscription_for(slug: str) -> Subscription:
    async with session_scope() as db:
        with bypass_tenant():
            return await db.scalar(
                select(Subscription).join(Subscription.tenant).where(
                    Subscription.provider_subscription_id.is_not(None)
                )
            ) or await db.scalar(select(Subscription))


@pytest.mark.asyncio
async def test_webhook_invalid_payload_returns_400(client: AsyncClient) -> None:
    """Garbled payload — mock provider raises on parse, handler returns 400."""
    r = await client.post(
        "/api/v1/webhooks/billing",
        content=b"not-json",
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_webhook_unknown_event_type_ignored(client: AsyncClient) -> None:
    payload = json.dumps({"id": "evt_test_1", "type": "customer.created", "data": {}}).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200
    assert r.json()["received"] == "true"


@pytest.mark.asyncio
async def test_webhook_payment_failed_marks_subscription_past_due(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    sub = await _subscription_for("acme")
    assert sub.provider_subscription_id is not None
    now = int(datetime.now(UTC).timestamp())

    payload = json.dumps({
        "id": "evt_pay_fail_1",
        "type": "invoice.payment_failed",
        "data": {
            "id": "in_fail_1",
            "subscription": sub.provider_subscription_id,
            "amount_due": 2900,
            "currency": "usd",
            "created": now,
            "due_date": now,
        },
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200

    async with session_scope() as db:
        with bypass_tenant():
            updated = await db.get(Subscription, sub.id)
            assert updated.status == SubscriptionStatus.PAST_DUE


@pytest.mark.asyncio
async def test_webhook_payment_succeeded_reactivates(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    sub = await _subscription_for("acme")
    now = int(datetime.now(UTC).timestamp())

    # First, fail once → past_due.
    fail = json.dumps({
        "id": "evt_pay_fail_2",
        "type": "invoice.payment_failed",
        "data": {
            "id": "in_2", "subscription": sub.provider_subscription_id,
            "amount_due": 2900, "currency": "usd", "created": now, "due_date": now,
        },
    }).encode()
    await client.post("/api/v1/webhooks/billing", content=fail)

    # Then succeed → active again.
    ok = json.dumps({
        "id": "evt_pay_ok_1",
        "type": "invoice.payment_succeeded",
        "data": {
            "id": "in_2", "subscription": sub.provider_subscription_id,
            "amount_paid": 2900, "currency": "usd", "created": now, "due_date": now,
        },
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=ok)
    assert r.status_code == 200

    async with session_scope() as db:
        with bypass_tenant():
            updated = await db.get(Subscription, sub.id)
            assert updated.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_webhook_for_unknown_subscription_returns_200(client: AsyncClient) -> None:
    """Provider may send events for subscriptions we don't know — must not 500."""
    now = int(datetime.now(UTC).timestamp())
    payload = json.dumps({
        "id": "evt_unknown",
        "type": "invoice.payment_succeeded",
        "data": {
            "id": "in_unknown", "subscription": "mock_sub_does_not_exist",
            "amount_paid": 100, "currency": "usd", "created": now, "due_date": now,
        },
    }).encode()
    r = await client.post("/api/v1/webhooks/billing", content=payload)
    assert r.status_code == 200
