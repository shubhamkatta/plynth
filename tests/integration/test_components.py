"""Integration tests for the per-product components system.

Covers admin CRUD, default-permissive access, per-user overrides
(enable + disable), revert-to-default by clearing the override,
inactive components, the /auth/me embed, and cross-tenant isolation.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import (
    auth,
    platform_admin_headers,
    product_headers,
    register_tenant,
)

ADMIN_BASE = "/api/v1/admin/products/producta/components"
ADMIN_B_BASE = "/api/v1/admin/products/productb/components"


def _comp(code: str, **kw) -> dict:
    body = {"code": code, "name": code.replace("-", " ").title()}
    body.update(kw)
    return body


# ---------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_create_and_list(client: AsyncClient) -> None:
    r = await client.post(
        ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "voice-overlay"
    assert r.json()["is_default_enabled"] is True

    listing = await client.get(ADMIN_BASE, headers=platform_admin_headers())
    assert listing.status_code == 200
    assert [c["code"] for c in listing.json()] == ["voice-overlay"]


@pytest.mark.asyncio
async def test_admin_duplicate_code_409(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    r = await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_admin_invalid_code_pattern_422(client: AsyncClient) -> None:
    r = await client.post(
        ADMIN_BASE, json=_comp("Voice_Overlay"), headers=platform_admin_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_patch_default(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    r = await client.patch(
        f"{ADMIN_BASE}/voice-overlay",
        json={"is_default_enabled": False, "description": "opt-in"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200
    assert r.json()["is_default_enabled"] is False
    assert r.json()["description"] == "opt-in"


@pytest.mark.asyncio
async def test_admin_patch_extra_field_422(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    r = await client.patch(
        f"{ADMIN_BASE}/voice-overlay",
        json={"weird_field": True},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_delete(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    r = await client.delete(f"{ADMIN_BASE}/voice-overlay", headers=platform_admin_headers())
    assert r.status_code == 204
    listing = await client.get(ADMIN_BASE, headers=platform_admin_headers())
    assert listing.json() == []


# ---------------------------------------------------------------------
# User-facing default access
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_permissive_user_sees_components(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    await client.post(ADMIN_BASE, json=_comp("morning-brief"), headers=platform_admin_headers())

    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/components", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    rows = {row["code"]: row for row in r.json()}
    assert rows["voice-overlay"]["is_enabled"] is True
    assert rows["voice-overlay"]["source"] == "default"
    assert rows["morning-brief"]["is_enabled"] is True


@pytest.mark.asyncio
async def test_default_off_component_hidden_until_override(client: AsyncClient) -> None:
    await client.post(
        ADMIN_BASE,
        json=_comp("alpha-feature", is_default_enabled=False),
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/components", headers=auth(tok["access_token"]))
    rows = {row["code"]: row for row in r.json()}
    assert rows["alpha-feature"]["is_enabled"] is False


@pytest.mark.asyncio
async def test_inactive_component_omitted(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    await client.patch(
        f"{ADMIN_BASE}/voice-overlay",
        json={"is_active": False},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    r = await client.get("/api/v1/components", headers=auth(tok["access_token"]))
    assert all(c["code"] != "voice-overlay" for c in r.json())


# ---------------------------------------------------------------------
# Per-user overrides
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_can_disable_for_user(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    user_id = me["id"]

    r = await client.put(
        f"/api/v1/users/{user_id}/components/voice-overlay",
        json={"is_enabled": False, "reason": "billing dispute"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_enabled"] is False
    assert r.json()["source"] == "override"
    assert r.json()["reason"] == "billing dispute"

    # Effective list now shows it disabled with source=override
    listing = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    rows = {row["code"]: row for row in listing}
    assert rows["voice-overlay"]["is_enabled"] is False
    assert rows["voice-overlay"]["source"] == "override"


@pytest.mark.asyncio
async def test_admin_can_enable_default_off_for_user(client: AsyncClient) -> None:
    await client.post(
        ADMIN_BASE,
        json=_comp("alpha-feature", is_default_enabled=False),
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()

    r = await client.put(
        f"/api/v1/users/{me['id']}/components/alpha-feature",
        json={"is_enabled": True, "reason": "early access"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["is_enabled"] is True


@pytest.mark.asyncio
async def test_clear_override_reverts_to_default(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()

    await client.put(
        f"/api/v1/users/{me['id']}/components/voice-overlay",
        json={"is_enabled": False}, headers=auth(tok["access_token"]),
    )
    r = await client.delete(
        f"/api/v1/users/{me['id']}/components/voice-overlay",
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 204

    listing = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    rows = {row["code"]: row for row in listing}
    assert rows["voice-overlay"]["is_enabled"] is True
    assert rows["voice-overlay"]["source"] == "default"


@pytest.mark.asyncio
async def test_override_unknown_component_404(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    r = await client.put(
        f"/api/v1/users/{me['id']}/components/nope",
        json={"is_enabled": True}, headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_override_cross_tenant_user_404(client: AsyncClient) -> None:
    """Owner of tenant A can't toggle a user in tenant B."""
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    tok_a = await register_tenant(client, slug="acme")
    tok_b = await register_tenant(client, slug="globex")
    me_b = (await client.get("/api/v1/auth/me", headers=auth(tok_b["access_token"]))).json()
    r = await client.put(
        f"/api/v1/users/{me_b['id']}/components/voice-overlay",
        json={"is_enabled": False},
        headers=auth(tok_a["access_token"]),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------
# /auth/me embed + cross-product isolation
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_embeds_components_map(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    await client.post(
        ADMIN_BASE,
        json=_comp("alpha-feature", is_default_enabled=False),
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    assert me["components"] == {"voice-overlay": True, "alpha-feature": False}


@pytest.mark.asyncio
async def test_cross_product_isolation(client: AsyncClient) -> None:
    """Components in productb are not visible to producta users."""
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    await client.post(ADMIN_B_BASE, json=_comp("workout-tracker"), headers=platform_admin_headers())

    tok_a = await register_tenant(client, slug="acme", product_slug="producta")
    r = await client.get(
        "/api/v1/components",
        headers={**auth(tok_a["access_token"]), **product_headers("producta")},
    )
    codes = {c["code"] for c in r.json()}
    assert codes == {"voice-overlay"}
