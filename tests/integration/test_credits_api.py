"""HTTP credit endpoints (grant + consume + wallets + ledger)."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


@pytest.mark.asyncio
async def test_trial_grants_initial_credits(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/credits/wallets", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    wallets = {w["feature_key"]: w for w in r.json()}
    assert "credits.ai_completion" in wallets
    # Free plan grants 100 credits at trial start.
    assert float(wallets["credits.ai_completion"]["balance"]) == 100.0


@pytest.mark.asyncio
async def test_grant_then_consume(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    g = await client.post(
        "/api/v1/credits/grant",
        json={"feature_key": "credits.ai_completion", "amount": "50",
              "reason": "promo", "reference": "promo-2026-05"},
        headers=auth(tok["access_token"]),
    )
    assert g.status_code == 200
    assert float(g.json()["balance"]) == 150.0

    c = await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "30",
              "reason": "completion", "reference": "req-001"},
        headers=auth(tok["access_token"]),
    )
    assert c.status_code == 200
    assert float(c.json()["balance"]) == 120.0


@pytest.mark.asyncio
async def test_consume_more_than_balance_returns_402(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "99999"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 402
    assert r.json()["code"] == "insufficient_credits"


@pytest.mark.asyncio
async def test_consume_idempotent_via_reference(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    body = {"feature_key": "credits.ai_completion", "amount": "10", "reference": "req-abc"}
    first = await client.post("/api/v1/credits/consume", json=body,
                              headers=auth(tok["access_token"]))
    second = await client.post("/api/v1/credits/consume", json=body,
                               headers=auth(tok["access_token"]))
    assert first.json()["balance"] == second.json()["balance"]


@pytest.mark.asyncio
async def test_ledger_records_movements(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "5"},
        headers=auth(tok["access_token"]),
    )
    r = await client.get("/api/v1/credits/ledger", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    entries = r.json()
    assert any(e["entry_type"] == "debit" and float(e["amount"]) == -5.0 for e in entries)
    assert any(e["entry_type"] == "grant" for e in entries)


@pytest.mark.asyncio
async def test_credit_wallets_isolated_between_tenants(client: AsyncClient) -> None:
    a = await register_tenant(client, slug="alpha")
    b = await register_tenant(client, slug="beta")
    # Tenant A consumes some credits.
    await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "20"},
        headers=auth(a["access_token"]),
    )
    # Tenant B's balance must still be the full 100.
    r = await client.get("/api/v1/credits/wallets", headers=auth(b["access_token"]))
    wallet = next(w for w in r.json() if w["feature_key"] == "credits.ai_completion")
    assert float(wallet["balance"]) == 100.0
