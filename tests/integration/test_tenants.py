"""Tenants API."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


@pytest.mark.asyncio
async def test_list_tenants_returns_self(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/tenants", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    slugs = [t["slug"] for t in r.json()]
    assert slugs == ["acme"]


@pytest.mark.asyncio
async def test_create_child_tenant(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme East", "slug": "acme-east"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "acme-east"
    assert body["is_root"] is False
    assert body["parent_id"] is not None

    # List now returns parent + child.
    listed = await client.get("/api/v1/tenants", headers=auth(tok["access_token"]))
    slugs = {t["slug"] for t in listed.json()}
    assert slugs == {"acme", "acme-east"}


@pytest.mark.asyncio
async def test_child_tenant_slug_must_be_unique(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/tenants",
        json={"name": "Child", "slug": "child"},
        headers=auth(tok["access_token"]),
    )
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Child Two", "slug": "child"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_child_under_someone_elses_tenant_is_forbidden(client: AsyncClient) -> None:
    tok_a = await register_tenant(client, slug="alpha")
    tok_b = await register_tenant(client, slug="beta")
    me_b = await client.get("/api/v1/auth/me", headers=auth(tok_b["access_token"]))
    beta_tenant_id = me_b.json()["tenant_id"]

    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Sneaky", "slug": "sneaky", "parent_id": beta_tenant_id},
        headers=auth(tok_a["access_token"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_tenant_name(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    tid = me.json()["tenant_id"]
    r = await client.patch(
        f"/api/v1/tenants/{tid}",
        json={"name": "Acme Renamed"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Renamed"


@pytest.mark.asyncio
async def test_deactivate_then_activate(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    tid = me.json()["tenant_id"]

    d = await client.post(f"/api/v1/tenants/{tid}/deactivate", headers=auth(tok["access_token"]))
    assert d.status_code == 200
    assert d.json()["status"] == "deactivated"

    a = await client.post(f"/api/v1/tenants/{tid}/activate", headers=auth(tok["access_token"]))
    assert a.status_code == 200
    assert a.json()["status"] == "active"


@pytest.mark.asyncio
async def test_grandchild_tenant_is_rejected(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r1 = await client.post(
        "/api/v1/tenants", json={"name": "Child", "slug": "child"},
        headers=auth(tok["access_token"]),
    )
    child_id = r1.json()["id"]
    r2 = await client.post(
        "/api/v1/tenants",
        json={"name": "Grandchild", "slug": "grandchild", "parent_id": child_id},
        headers=auth(tok["access_token"]),
    )
    # Forbidden because parent_id != user's tenant_id.
    assert r2.status_code == 403
