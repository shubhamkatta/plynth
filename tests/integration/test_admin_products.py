"""Platform-admin product CRUD."""

import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_headers


@pytest.mark.asyncio
async def test_admin_endpoints_require_token(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/products")
    assert r.status_code == 401
    r = await client.get("/api/v1/admin/products",
                         headers={"X-Platform-Admin-Token": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_products_returns_seeded_pair(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/products", headers=platform_admin_headers())
    assert r.status_code == 200
    slugs = {p["slug"] for p in r.json()}
    assert {"producta", "productb"}.issubset(slugs)


@pytest.mark.asyncio
async def test_create_product_then_register_inside_it(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "Brand New", "slug": "brandnew", "description": "fresh"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["slug"] == "brandnew"

    # Register a tenant inside the new product. Plans don't exist yet so
    # start_trial will fail — but the validation error happens *after*
    # the product lookup, so we know the slug resolved.
    reg = await client.post(
        "/api/v1/auth/register",
        json={"tenant_name": "T", "tenant_slug": "t",
              "email": "owner@t.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "brandnew"},
    )
    # The trial expects a plan; without one, we get 422.
    assert reg.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_product_slug_conflicts(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "A", "slug": "producta"},  # already seeded
        headers=platform_admin_headers(),
    )
    assert r.status_code == 409
