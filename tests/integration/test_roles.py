"""Roles + RBAC enforcement."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


@pytest.mark.asyncio
async def test_list_system_roles_visible(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/roles", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    names = {role["name"] for role in r.json()}
    assert {"owner", "admin", "member"}.issubset(names)


@pytest.mark.asyncio
async def test_list_permissions_returns_catalog(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/roles/permissions", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    codes = set(r.json())
    assert "users:read" in codes
    assert "subscriptions:purchase" in codes
    assert "*:*" in codes


@pytest.mark.asyncio
async def test_create_custom_role(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/roles",
        json={"name": "auditor", "description": "Read-only auditor",
              "permission_codes": ["users:read", "audit:read"]},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "auditor"
    assert set(body["permissions"]) == {"users:read", "audit:read"}


@pytest.mark.asyncio
async def test_create_role_with_unknown_permission_404s(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/roles",
        json={"name": "weird", "permission_codes": ["nope:nope"]},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_custom_role_replaces_permissions(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    created = await client.post(
        "/api/v1/roles",
        json={"name": "switcher", "permission_codes": ["users:read"]},
        headers=auth(tok["access_token"]),
    )
    rid = created.json()["id"]
    r = await client.patch(
        f"/api/v1/roles/{rid}",
        json={"permission_codes": ["audit:read", "credits:read"]},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    assert set(r.json()["permissions"]) == {"audit:read", "credits:read"}


@pytest.mark.asyncio
async def test_system_roles_are_immutable(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    roles = await client.get("/api/v1/roles", headers=auth(tok["access_token"]))
    owner = next(r for r in roles.json() if r["name"] == "owner")
    r = await client.patch(
        f"/api/v1/roles/{owner['id']}",
        json={"description": "hack"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_assign_role_binds_user(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    user_resp = await client.post(
        "/api/v1/users",
        json={"email": "bind@acme.example.com", "role_codes": ["member"]},
        headers=auth(tok["access_token"]),
    )
    uid = user_resp.json()["id"]

    roles = await client.get("/api/v1/roles", headers=auth(tok["access_token"]))
    admin_role = next(r for r in roles.json() if r["name"] == "admin")

    r = await client.post(
        "/api/v1/roles/assign",
        json={"user_id": uid, "role_id": admin_role["id"]},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_unauthorized_blocked_on_protected_endpoints(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users")
    assert r.status_code == 401
    r = await client.get("/api/v1/roles")
    assert r.status_code == 401
