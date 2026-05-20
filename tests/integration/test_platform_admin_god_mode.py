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
