"""Plan catalog."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, product_headers, register_tenant


@pytest.mark.asyncio
async def test_list_plans_requires_product_header(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_plans_public_only(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans", headers=product_headers("producta"))
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert codes == {"free", "pro"}  # enterprise is non-public


@pytest.mark.asyncio
async def test_plan_features_included(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans", headers=product_headers("producta"))
    pro = next(p for p in r.json() if p["code"] == "pro")
    feature_keys = {f["feature_key"] for f in pro["features"]}
    assert {"seats", "credits.ai_completion"}.issubset(feature_keys)


@pytest.mark.asyncio
async def test_create_plan_in_actor_product(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/plans",
        json={
            "code": "custom-plan",
            "name": "Custom",
            "price_cents": 1500,
            "currency": "USD",
            "interval": "month",
            "trial_days": 7,
            "features": [
                {"feature_key": "seats", "limit_value": "5"},
                {"feature_key": "credits.ai_completion", "credit_amount": "500"},
            ],
        },
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "custom-plan"
    assert len(body["features"]) == 2


@pytest.mark.asyncio
async def test_create_duplicate_plan_code_conflicts(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    payload = {
        "code": "dup-plan", "name": "Dup", "price_cents": 100,
        "currency": "USD", "interval": "month", "features": [],
    }
    a = await client.post("/api/v1/plans", json=payload, headers=auth(tok["access_token"]))
    assert a.status_code == 201
    b = await client.post("/api/v1/plans", json=payload, headers=auth(tok["access_token"]))
    assert b.status_code == 409


@pytest.mark.asyncio
async def test_same_plan_code_allowed_across_products(client: AsyncClient) -> None:
    """`(product_id, code)` is unique, so same code can live in producta + productb."""
    a = await register_tenant(client, slug="acme-a", product_slug="producta")
    b = await register_tenant(client, slug="acme-b", product_slug="productb")
    payload = {
        "code": "shared", "name": "Shared", "price_cents": 100,
        "currency": "USD", "interval": "month", "features": [],
    }
    ra = await client.post("/api/v1/plans", json=payload, headers=auth(a["access_token"], "producta"))
    rb = await client.post("/api/v1/plans", json=payload, headers=auth(b["access_token"], "productb"))
    assert ra.status_code == 201
    assert rb.status_code == 201


@pytest.mark.asyncio
async def test_update_plan(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/plans",
        json={"code": "updme", "name": "OrigName", "price_cents": 100,
              "currency": "USD", "interval": "month", "features": []},
        headers=auth(tok["access_token"]),
    )
    r = await client.patch(
        "/api/v1/plans/updme",
        json={"name": "New Name", "price_cents": 200},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "New Name"
    assert body["price_cents"] == 200
