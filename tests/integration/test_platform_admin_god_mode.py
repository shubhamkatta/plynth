"""Platform-admin token authenticates as a god user on tenant-scoped routes.

The PLATFORM_ADMIN_TOKEN is meant to give a true super-user across every
product, not just /admin/products. These tests cover that contract:
- Admin token + X-Product-Slug → all RBAC-gated routes accept the call.
- Admin token without X-Product-Slug → 422 (which product to operate on?).
- Wrong / missing admin token + no JWT → 401 (existing behavior).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_headers, product_headers


def admin_scope(slug: str = "producta") -> dict[str, str]:
    return {**platform_admin_headers(), **product_headers(slug)}


@pytest.mark.asyncio
async def test_admin_token_lists_tenants_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=admin_scope())
    assert r.status_code == 200, r.text
    # At minimum the seeded root tenant for producta should be visible.
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_admin_token_lists_users_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_roles_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/roles", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_plans_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_permissions(client: AsyncClient) -> None:
    # /roles/permissions is RBAC-gated; admin should pass.
    r = await client.get("/api/v1/roles/permissions", headers=admin_scope())
    assert r.status_code == 200, r.text
    assert "*:*" in r.json()


@pytest.mark.asyncio
async def test_admin_token_without_product_header_is_422(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=platform_admin_headers())
    # ValidationFailed → 422 (the dep raises before route runs).
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_no_token_no_jwt_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=product_headers())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_admin_token_falls_through_and_401s(client: AsyncClient) -> None:
    # Wrong token isn't accepted as god-mode; without a JWT it's "missing bearer".
    headers = {**product_headers(), "X-Platform-Admin-Token": "wrong"}
    r = await client.get("/api/v1/tenants", headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_bootstrap_root_tenant_in_empty_product(client: AsyncClient) -> None:
    """Empty product has no tenants — admin must be able to create the first
    root tenant directly (parent_id implicitly None)."""
    # Create a fresh product via admin so it's guaranteed empty.
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "Fresh", "slug": "fresh-bootstrap"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text

    # Admin lists tenants in the empty product → []
    r = await client.get(
        "/api/v1/tenants",
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 200
    assert r.json() == []

    # Admin creates the first root tenant — no parent_id.
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Root Co", "slug": "root-co"},
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "root-co"
    assert body["is_root"] is True
    assert body["parent_id"] is None

    # Now admin can list it.
    r = await client.get(
        "/api/v1/tenants",
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 200
    assert any(t["slug"] == "root-co" for t in r.json())


@pytest.mark.asyncio
async def test_admin_can_create_child_tenant_in_populated_product(
    client: AsyncClient,
) -> None:
    """When a product already has a root tenant, admin's effective tenant
    becomes that root and child creation works without parent_id."""
    # Seed a product with a root tenant via normal register flow.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Populated", "slug": "populated-prod"},
        headers=platform_admin_headers(),
    )
    # Admin creates the root directly (no need to register a user).
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Pop Root", "slug": "pop-root"},
        headers={**platform_admin_headers(), "X-Product-Slug": "populated-prod"},
    )
    assert r.status_code == 201, r.text

    # Admin creates a child of the root — parent_id resolves to root, not NIL.
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Pop Child", "slug": "pop-child"},
        headers={**platform_admin_headers(), "X-Product-Slug": "populated-prod"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "pop-child"
    assert body["is_root"] is False
    assert body["parent_id"] is not None
