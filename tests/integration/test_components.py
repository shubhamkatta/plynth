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
async def test_admin_underscore_code_accepted(client: AsyncClient) -> None:
    """Snake_case codes (e.g. Mayva's `ai_receptionist`) are valid — the
    code pattern allows hyphen or underscore, matching plan / feature-key
    code style."""
    r = await client.post(
        ADMIN_BASE, json=_comp("ai_receptionist"), headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "ai_receptionist"
    # And it round-trips through the per-code admin path param.
    patched = await client.patch(
        f"{ADMIN_BASE}/ai_receptionist",
        json={"description": "AI front desk"},
        headers=platform_admin_headers(),
    )
    assert patched.status_code == 200, patched.text


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
# Plan-driven gating (required_plan_codes)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_with_required_plan_codes(client: AsyncClient) -> None:
    r = await client.post(
        ADMIN_BASE,
        json={"code": "pro-only", "name": "Pro Only",
              "required_plan_codes": ["pro", "enterprise"]},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["required_plan_codes"] == ["pro", "enterprise"]


@pytest.mark.asyncio
async def test_free_user_blocked_from_paid_component(client: AsyncClient) -> None:
    """User on the seeded Free plan does NOT see a `pro`-gated component as enabled."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro", "enterprise"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is False
    assert by_code["voice-overlay"]["source"] == "plan"
    assert by_code["voice-overlay"]["required_plan_codes"] == ["pro", "enterprise"]


@pytest.mark.asyncio
async def test_pro_user_gets_paid_component(client: AsyncClient) -> None:
    """After upgrading to pro, the user sees the same component as enabled."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro", "enterprise"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    # Purchase the pro plan to flip the tenant's subscription.
    purchase = await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    assert purchase.status_code == 200, purchase.text

    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is True
    assert by_code["voice-overlay"]["source"] == "default"
    # On the qualifying path, the required_plan_codes hint isn't returned —
    # the client doesn't need it because the gate didn't fire.
    assert by_code["voice-overlay"]["required_plan_codes"] is None


@pytest.mark.asyncio
async def test_per_user_override_beats_plan_gate(client: AsyncClient) -> None:
    """A grant-by-override lets a free user access a pro-only component."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    # Owner has *:*, so can self-override.
    grant = await client.put(
        f"/api/v1/users/{me['id']}/components/voice-overlay",
        json={"is_enabled": True, "reason": "beta access"},
        headers=auth(tok["access_token"]),
    )
    assert grant.status_code == 200, grant.text
    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is True
    assert by_code["voice-overlay"]["source"] == "override"


@pytest.mark.asyncio
async def test_per_user_override_can_disable_qualifying_plan_user(client: AsyncClient) -> None:
    """A disable-by-override revokes a pro user from a pro-only component."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    await client.put(
        f"/api/v1/users/{me['id']}/components/voice-overlay",
        json={"is_enabled": False, "reason": "billing dispute"},
        headers=auth(tok["access_token"]),
    )
    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is False
    assert by_code["voice-overlay"]["source"] == "override"


@pytest.mark.asyncio
async def test_me_components_reflects_plan_gate(client: AsyncClient) -> None:
    """The /me embed should mirror the plan gating in a single map."""
    await client.post(
        ADMIN_BASE,
        json={"code": "everyone", "name": "Everyone"},
        headers=platform_admin_headers(),
    )
    await client.post(
        ADMIN_BASE,
        json={"code": "pro-only", "name": "Pro Only",
              "required_plan_codes": ["pro", "enterprise"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    assert me["components"] == {"everyone": True, "pro-only": False}


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


# ---------------------------------------------------------------------
# Per-tenant overrides (Option B — ops grants)
# ---------------------------------------------------------------------

async def _tenant_id_for(client: AsyncClient, token: str) -> str:
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    return me["tenant_id"]


@pytest.mark.asyncio
async def test_tenant_override_grants_plan_gated_component(client: AsyncClient) -> None:
    """Ops grants a pro-only component to a free tenant via tenant override."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    tenant_id = await _tenant_id_for(client, tok["access_token"])

    grant = await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_id}/voice-overlay",
        json={"is_enabled": True, "reason": "comped trial"},
        headers=platform_admin_headers(),
    )
    assert grant.status_code == 200, grant.text
    assert grant.json()["is_enabled"] is True
    assert grant.json()["source"] == "tenant_override"

    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is True
    assert by_code["voice-overlay"]["source"] == "tenant_override"
    assert by_code["voice-overlay"]["reason"] == "comped trial"


@pytest.mark.asyncio
async def test_tenant_override_can_revoke_default_on_component(client: AsyncClient) -> None:
    """Tenant override flips a default-on component off for everyone in the tenant."""
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    tok = await register_tenant(client, slug="acme")
    tenant_id = await _tenant_id_for(client, tok["access_token"])

    await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_id}/voice-overlay",
        json={"is_enabled": False, "reason": "tenant-wide disable"},
        headers=platform_admin_headers(),
    )
    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is False
    assert by_code["voice-overlay"]["source"] == "tenant_override"


@pytest.mark.asyncio
async def test_user_override_beats_tenant_override(client: AsyncClient) -> None:
    """Per-user override always wins over tenant override."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    tenant_id = me["tenant_id"]

    # Tenant override: enabled for whole tenant.
    await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_id}/voice-overlay",
        json={"is_enabled": True},
        headers=platform_admin_headers(),
    )
    # User override: this one user is disabled.
    await client.put(
        f"/api/v1/users/{me['id']}/components/voice-overlay",
        json={"is_enabled": False, "reason": "personal opt-out"},
        headers=auth(tok["access_token"]),
    )
    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    assert by_code["voice-overlay"]["is_enabled"] is False
    assert by_code["voice-overlay"]["source"] == "override"


@pytest.mark.asyncio
async def test_clear_tenant_override_reverts_to_plan_gate(client: AsyncClient) -> None:
    """Removing the tenant override reverts to the plan-gated default."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    tenant_id = await _tenant_id_for(client, tok["access_token"])

    await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_id}/voice-overlay",
        json={"is_enabled": True},
        headers=platform_admin_headers(),
    )
    cleared = await client.delete(
        f"{ADMIN_BASE}/tenants/{tenant_id}/voice-overlay",
        headers=platform_admin_headers(),
    )
    assert cleared.status_code == 204

    rows = (await client.get("/api/v1/components", headers=auth(tok["access_token"]))).json()
    by_code = {row["code"]: row for row in rows}
    # Free tenant reverts to plan-gated False.
    assert by_code["voice-overlay"]["is_enabled"] is False
    assert by_code["voice-overlay"]["source"] == "plan"


@pytest.mark.asyncio
async def test_list_tenant_components_admin(client: AsyncClient) -> None:
    """Admin tenant-effective listing returns sources without consulting user overrides."""
    await client.post(ADMIN_BASE, json=_comp("everyone"), headers=platform_admin_headers())
    await client.post(
        ADMIN_BASE,
        json={"code": "pro-only", "name": "Pro Only", "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok = await register_tenant(client, slug="acme")
    me = (await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))).json()
    tenant_id = me["tenant_id"]

    # Grant pro-only to this tenant.
    await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_id}/pro-only",
        json={"is_enabled": True, "reason": "comped"},
        headers=platform_admin_headers(),
    )
    # User-level override should NOT influence the admin tenant view.
    await client.put(
        f"/api/v1/users/{me['id']}/components/pro-only",
        json={"is_enabled": False, "reason": "test-only"},
        headers=auth(tok["access_token"]),
    )
    r = await client.get(
        f"{ADMIN_BASE}/tenants/{tenant_id}",
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200, r.text
    by_code = {row["code"]: row for row in r.json()}
    assert by_code["everyone"]["source"] == "default"
    assert by_code["everyone"]["is_enabled"] is True
    assert by_code["pro-only"]["source"] == "tenant_override"
    assert by_code["pro-only"]["is_enabled"] is True


@pytest.mark.asyncio
async def test_tenant_override_isolated_per_tenant(client: AsyncClient) -> None:
    """Tenant override for Acme must not leak into Globex."""
    await client.post(
        ADMIN_BASE,
        json={"code": "voice-overlay", "name": "Voice Overlay",
              "required_plan_codes": ["pro"]},
        headers=platform_admin_headers(),
    )
    tok_a = await register_tenant(client, slug="acme")
    tok_b = await register_tenant(client, slug="globex")
    tenant_a = await _tenant_id_for(client, tok_a["access_token"])

    await client.put(
        f"{ADMIN_BASE}/tenants/{tenant_a}/voice-overlay",
        json={"is_enabled": True},
        headers=platform_admin_headers(),
    )
    rows_b = (await client.get("/api/v1/components", headers=auth(tok_b["access_token"]))).json()
    by_code_b = {row["code"]: row for row in rows_b}
    assert by_code_b["voice-overlay"]["is_enabled"] is False
    assert by_code_b["voice-overlay"]["source"] == "plan"


@pytest.mark.asyncio
async def test_tenant_override_unknown_tenant_404(client: AsyncClient) -> None:
    await client.post(ADMIN_BASE, json=_comp("voice-overlay"), headers=platform_admin_headers())
    bogus = "11111111-1111-1111-1111-111111111111"
    r = await client.put(
        f"{ADMIN_BASE}/tenants/{bogus}/voice-overlay",
        json={"is_enabled": True},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 404
