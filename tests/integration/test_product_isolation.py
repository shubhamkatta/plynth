"""Cross-product isolation: same slug / email in two products, never visible
across, JWT mismatch rejected."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, auth_no_product_header, product_headers, register_tenant


@pytest.mark.asyncio
async def test_same_tenant_slug_in_two_products(client: AsyncClient) -> None:
    """Both products allow `acme` as a tenant slug — they're independent."""
    a = await register_tenant(client, slug="acme", product_slug="producta")
    b = await register_tenant(
        client, slug="acme", email="owner@acme-b.example.com", product_slug="productb",
    )

    me_a = await client.get("/api/v1/auth/me", headers=auth(a["access_token"], "producta"))
    me_b = await client.get("/api/v1/auth/me", headers=auth(b["access_token"], "productb"))
    assert me_a.status_code == 200
    assert me_b.status_code == 200
    assert me_a.json()["product_id"] != me_b.json()["product_id"]


@pytest.mark.asyncio
async def test_tenant_listing_isolated_per_product(client: AsyncClient) -> None:
    a = await register_tenant(client, slug="alpha", product_slug="producta")
    await register_tenant(client, slug="alpha", product_slug="productb")
    listed = await client.get("/api/v1/tenants", headers=auth(a["access_token"], "producta"))
    slugs = [t["slug"] for t in listed.json()]
    # Only the product-A tenant is visible.
    assert slugs == ["alpha"]


@pytest.mark.asyncio
async def test_user_listing_isolated_per_product(client: AsyncClient) -> None:
    a = await register_tenant(client, slug="alpha", product_slug="producta")
    b = await register_tenant(client, slug="alpha", product_slug="productb")
    a_users = await client.get("/api/v1/users", headers=auth(a["access_token"], "producta"))
    b_users = await client.get("/api/v1/users", headers=auth(b["access_token"], "productb"))
    a_emails = {u["email"] for u in a_users.json()}
    b_emails = {u["email"] for u in b_users.json()}
    assert a_emails == {"owner@alpha.example.com"}
    assert b_emails == {"owner@alpha.example.com"}
    # Distinct user IDs even though emails are the same.
    a_ids = {u["id"] for u in a_users.json()}
    b_ids = {u["id"] for u in b_users.json()}
    assert a_ids.isdisjoint(b_ids)


@pytest.mark.asyncio
async def test_plans_listing_per_product(client: AsyncClient) -> None:
    a = await client.get("/api/v1/plans", headers=product_headers("producta"))
    b = await client.get("/api/v1/plans", headers=product_headers("productb"))
    a_ids = {p["id"] for p in a.json()}
    b_ids = {p["id"] for p in b.json()}
    a_codes = {p["code"] for p in a.json()}
    b_codes = {p["code"] for p in b.json()}
    # Seeded codes present in both, distinct IDs (separate rows per product).
    assert {"free", "pro"}.issubset(a_codes)
    assert {"free", "pro"}.issubset(b_codes)
    assert a_ids.isdisjoint(b_ids)


@pytest.mark.asyncio
async def test_jwt_product_header_mismatch_forbidden(client: AsyncClient) -> None:
    """A token issued by Product A presented with X-Product-Slug: productb → 403."""
    a = await register_tenant(client, slug="acme", product_slug="producta")
    r = await client.get(
        "/api/v1/auth/me",
        headers=auth(a["access_token"], "productb"),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_jwt_alone_works_without_header(client: AsyncClient) -> None:
    """Authenticated routes also work without the X-Product-Slug header —
    the JWT pid claim provides the context."""
    a = await register_tenant(client, slug="acme", product_slug="producta")
    r = await client.get("/api/v1/auth/me",
                         headers=auth_no_product_header(a["access_token"]))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_credits_isolated_per_product(client: AsyncClient) -> None:
    """A consume in Product A doesn't touch the wallet in Product B."""
    a = await register_tenant(client, slug="alpha", product_slug="producta")
    b = await register_tenant(client, slug="alpha", product_slug="productb")
    await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "30"},
        headers=auth(a["access_token"], "producta"),
    )
    r = await client.get("/api/v1/credits/wallets", headers=auth(b["access_token"], "productb"))
    wallet = next(w for w in r.json() if w["feature_key"] == "credits.ai_completion")
    # Untouched.
    assert float(wallet["balance"]) == 100.0


@pytest.mark.asyncio
async def test_login_to_wrong_product_fails(client: AsyncClient) -> None:
    """Register in Product A, try to login from Product B → 401."""
    await register_tenant(client, slug="acme", product_slug="producta")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "S3cretPassword!"},
        headers=product_headers("productb"),
    )
    assert r.status_code == 401
