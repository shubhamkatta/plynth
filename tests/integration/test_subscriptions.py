"""Subscription endpoints — driven by the mock billing provider."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


@pytest.mark.asyncio
async def test_register_activates_free_subscription(client: AsyncClient) -> None:
    """The seeded Free plan ($0) is the cheapest public plan, so registration
    activates it immediately — no trial, never expires. See start_trial()
    in app/services/subscription.py for the $0-vs-paid branching."""
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/subscription", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["has_access"] is True
    assert body["trial_end"] is None


@pytest.mark.asyncio
async def test_purchase_plan(client: AsyncClient) -> None:
    """Purchasing a PAID plan starts the card-on-file free trial: the mandate is
    authorized now but the customer is NOT charged until trial end, so the
    subscription lands in TRIAL (not ACTIVE) with access and a future
    trial_end. It flips to ACTIVE later via the subscription webhook."""
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_code"] == "pro"
    assert body["status"] == "trial"
    assert body["has_access"] is True
    assert body["trial_end"] is not None


@pytest.mark.asyncio
async def test_upgrade_then_downgrade(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "free"},
        headers=auth(tok["access_token"]),
    )
    up = await client.post(
        "/api/v1/subscription/change",
        json={"plan_code": "pro", "proration": True},
        headers=auth(tok["access_token"]),
    )
    assert up.status_code == 200, up.text
    assert up.json()["plan_code"] == "pro"

    down = await client.post(
        "/api/v1/subscription/change",
        json={"plan_code": "free", "proration": False},
        headers=auth(tok["access_token"]),
    )
    assert down.status_code == 200
    assert down.json()["plan_code"] == "free"


@pytest.mark.asyncio
async def test_change_to_same_plan_conflicts(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    r = await client.post(
        "/api/v1/subscription/change",
        json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_at_period_end(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    r = await client.post(
        "/api/v1/subscription/cancel",
        json={"at_period_end": True, "reason": "trying something else"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cancel_at_period_end"] is True
    # Paid purchase starts a trial; cancelling at period end keeps access until
    # then (status is unchanged — TRIAL here, not flipped to cancelled).
    assert body["status"] == "trial"
    assert body["has_access"] is True


@pytest.mark.asyncio
async def test_cancel_immediately(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    r = await client.post(
        "/api/v1/subscription/cancel",
        json={"at_period_end": False},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["has_access"] is False


@pytest.mark.asyncio
async def test_purchase_unknown_plan_404s(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "no-such-plan"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404
