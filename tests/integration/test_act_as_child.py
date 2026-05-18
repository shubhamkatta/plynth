"""Parent → child tenant access (`X-Acting-Tenant-Slug`).

Covers:
- Discovery via GET /tenants/children
- Successful switching (owner, scoped-binding admin)
- Negative paths (no perm, non-descendant, unknown slug, cross-product)
- Config gates (product setting + parent tenant setting)
- Scope-aware permission evaluation
- Audit trail records `acting_from_tenant_id`
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.security import hash_password
from app.core.tenant import bypass_product, bypass_tenant
from app.models.audit import AuditLog
from app.models.product import Product
from app.models.role import Role, UserRole
from app.models.tenant import Tenant
from app.models.user import User
from tests.conftest import (
    auth,
    auth_acting_as,
    product_headers,
    register_tenant,
)


async def _provision_parent_with_children(
    client: AsyncClient,
    *,
    parent_slug: str = "parent-co",
    children: tuple[str, ...] = ("east", "west"),
) -> tuple[dict, list[str]]:
    """Register a parent tenant + create N child tenants under it.
    Returns (owner_tokens, child_slugs)."""
    owner = await register_tenant(client, slug=parent_slug)
    created = []
    for child in children:
        r = await client.post(
            "/api/v1/tenants",
            json={"name": child.title(), "slug": child},
            headers=auth(owner["access_token"]),
        )
        assert r.status_code == 201, r.text
        created.append(child)
    return owner, created


async def _set_member_password(email: str, password: str) -> None:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            u = await db.scalar(select(User).where(User.email == email))
            assert u is not None
            u.password_hash = hash_password(password)
            u.is_verified = True


async def _login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=product_headers("producta"),
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ---------- discovery -------------------------------------------------------

@pytest.mark.asyncio
async def test_list_children_shows_can_act_as_true_for_owner(client: AsyncClient) -> None:
    owner, children = await _provision_parent_with_children(client)
    r = await client.get("/api/v1/tenants/children", headers=auth(owner["access_token"]))
    assert r.status_code == 200
    rows = r.json()
    assert {c["slug"] for c in rows} == set(children)
    for c in rows:
        assert c["can_act_as"] is True
        assert c["reason"] is None


@pytest.mark.asyncio
async def test_member_sees_children_but_cannot_act(client: AsyncClient) -> None:
    """Member doesn't have `tenants:act_as_child`, so every child returns False."""
    owner, children = await _provision_parent_with_children(client)
    # Invite a member.
    invited = await client.post(
        "/api/v1/users",
        json={"email": "mem@parent-co.example.com", "role_codes": ["member"]},
        headers=auth(owner["access_token"]),
    )
    assert invited.status_code == 201
    await _set_member_password("mem@parent-co.example.com", "MemberPwd99!")
    member_tok = await _login(client, "mem@parent-co.example.com", "MemberPwd99!")

    r = await client.get("/api/v1/tenants/children", headers=auth(member_tok))
    assert r.status_code == 200
    rows = r.json()
    assert all(c["can_act_as"] is False for c in rows)
    assert all("permission" in c["reason"] for c in rows)


@pytest.mark.asyncio
async def test_list_children_reflects_product_gate(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client)
    # Disable at product level.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            p = await db.scalar(select(Product).where(Product.slug == "producta"))
            p.settings = {"features": {"allow_parent_child_access": False}}

    r = await client.get("/api/v1/tenants/children", headers=auth(owner["access_token"]))
    rows = r.json()
    assert all(c["can_act_as"] is False for c in rows)
    assert any("product" in (c["reason"] or "") for c in rows)
    # Reset for other tests.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            p = await db.scalar(select(Product).where(Product.slug == "producta"))
            p.settings = {}


@pytest.mark.asyncio
async def test_list_children_reflects_parent_gate(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="locked-parent")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            parent = await db.scalar(
                select(Tenant).where(Tenant.slug == "locked-parent")
            )
            parent.settings = {"allow_child_access": False}
    r = await client.get("/api/v1/tenants/children", headers=auth(owner["access_token"]))
    rows = r.json()
    assert all(c["can_act_as"] is False for c in rows)
    assert all("parent tenant" in (c["reason"] or "") for c in rows)


# ---------- switching: success ----------------------------------------------

@pytest.mark.asyncio
async def test_owner_acts_as_child_and_sees_child_users(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client)
    # Invite a user inside the parent first — should NOT appear when acting as child.
    await client.post(
        "/api/v1/users",
        json={"email": "parent-only@parent-co.example.com", "role_codes": ["member"]},
        headers=auth(owner["access_token"]),
    )
    # Now act as child east and invite someone inside it.
    headers = auth_acting_as(owner["access_token"], "east")
    r = await client.post(
        "/api/v1/users",
        json={"email": "east-only@parent-co.example.com", "role_codes": ["member"]},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # Listing users while acting as east → only east users.
    listed = await client.get("/api/v1/users", headers=headers)
    emails = {u["email"] for u in listed.json()}
    assert emails == {"east-only@parent-co.example.com"}

    # Listing back in home → only parent users.
    home = await client.get("/api/v1/users", headers=auth(owner["access_token"]))
    home_emails = {u["email"] for u in home.json()}
    assert "parent-only@parent-co.example.com" in home_emails
    assert "east-only@parent-co.example.com" not in home_emails


@pytest.mark.asyncio
async def test_act_as_no_op_when_targeting_home_tenant(client: AsyncClient) -> None:
    """Sending the header pointing to your own tenant is accepted (no-op)."""
    owner, _ = await _provision_parent_with_children(client)
    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(owner["access_token"], "parent-co"),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_scoped_role_binding_unlocks_act_as_for_that_child(
    client: AsyncClient,
) -> None:
    """A member who has an explicit role binding inside child Y can switch
    into Y, even without the global act_as_child permission."""
    owner, _ = await _provision_parent_with_children(
        client, parent_slug="scope-parent", children=("only-this",),
    )
    invited = await client.post(
        "/api/v1/users",
        json={"email": "scoped@scope-parent.example.com", "role_codes": ["member"]},
        headers=auth(owner["access_token"]),
    )
    user_id = invited.json()["id"]

    # Bind the user with scope_tenant_id = child.id (admin in only-this).
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            child = await db.scalar(select(Tenant).where(Tenant.slug == "only-this"))
            admin = await db.scalar(
                select(Role).where(
                    Role.product_id == child.product_id,
                    Role.tenant_id.is_(None),
                    Role.name == "admin",
                )
            )
            db.add(UserRole(
                product_id=child.product_id, user_id=user_id,
                role_id=admin.id, scope_tenant_id=child.id,
            ))
    await _set_member_password("scoped@scope-parent.example.com", "ScopedPwd99!")
    tok = await _login(client, "scoped@scope-parent.example.com", "ScopedPwd99!")

    # Switching into only-this succeeds.
    r = await client.get("/api/v1/users", headers=auth_acting_as(tok, "only-this"))
    assert r.status_code == 200


# ---------- switching: negative paths ---------------------------------------

@pytest.mark.asyncio
async def test_member_without_perm_or_binding_cannot_switch(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="deny-parent")
    await client.post(
        "/api/v1/users",
        json={"email": "weak@deny-parent.example.com", "role_codes": ["member"]},
        headers=auth(owner["access_token"]),
    )
    await _set_member_password("weak@deny-parent.example.com", "WeakPwd9999!")
    weak_tok = await _login(client, "weak@deny-parent.example.com", "WeakPwd9999!")

    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(weak_tok, "east"),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_unknown_tenant_slug_returns_404(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="unknown-test")
    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(owner["access_token"], "no-such-tenant"),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_descendant_tenant_is_forbidden(client: AsyncClient) -> None:
    """A different root tenant (not a child) cannot be acted-as."""
    owner_a, _ = await _provision_parent_with_children(client, parent_slug="org-a")
    # Sibling root tenant.
    await register_tenant(client, slug="org-b", email="b@org-b.example.com")
    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(owner_a["access_token"], "org-b"),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cross_product_act_as_is_404(client: AsyncClient) -> None:
    """The header is resolved within the user's product; a slug from
    another product isn't found."""
    owner, _ = await _provision_parent_with_children(client, parent_slug="cross-a")
    # Create same-slug child in productb.
    other = await register_tenant(client, slug="cross-a", product_slug="productb")
    await client.post(
        "/api/v1/tenants", json={"name": "Distant", "slug": "distant"},
        headers=auth(other["access_token"], "productb"),
    )
    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(owner["access_token"], "distant"),
    )
    assert r.status_code == 404


# ---------- config gates ----------------------------------------------------

@pytest.mark.asyncio
async def test_product_disabled_blocks_switch(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="gate-product")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            p = await db.scalar(select(Product).where(Product.slug == "producta"))
            p.settings = {"features": {"allow_parent_child_access": False}}
    try:
        r = await client.get(
            "/api/v1/users",
            headers=auth_acting_as(owner["access_token"], "east"),
        )
        assert r.status_code == 403
        assert "product" in r.json()["message"]
    finally:
        async with session_scope() as db:
            with bypass_product(), bypass_tenant():
                p = await db.scalar(select(Product).where(Product.slug == "producta"))
                p.settings = {}


@pytest.mark.asyncio
async def test_parent_tenant_disabled_blocks_switch(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="gate-tenant")
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            parent = await db.scalar(
                select(Tenant).where(Tenant.slug == "gate-tenant")
            )
            parent.settings = {"allow_child_access": False}
    r = await client.get(
        "/api/v1/users",
        headers=auth_acting_as(owner["access_token"], "east"),
    )
    assert r.status_code == 403
    assert "tenant" in r.json()["message"]


# ---------- audit trail -----------------------------------------------------

@pytest.mark.asyncio
async def test_actions_under_act_as_record_acting_from(client: AsyncClient) -> None:
    owner, _ = await _provision_parent_with_children(client, parent_slug="audit-parent")
    # Capture parent + child tenant ids.
    me = await client.get("/api/v1/auth/me", headers=auth(owner["access_token"]))
    parent_tid = me.json()["tenant_id"]
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            child = await db.scalar(select(Tenant).where(Tenant.slug == "east"))
            child_tid = str(child.id)

    # Action under acting-as.
    await client.post(
        "/api/v1/users",
        json={"email": "trail@audit.example.com", "role_codes": ["member"]},
        headers=auth_acting_as(owner["access_token"], "east"),
    )
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "user.invite",
                    AuditLog.tenant_id == child.id,
                ).order_by(AuditLog.created_at.desc())
            )
    assert row is not None
    assert str(row.tenant_id) == child_tid
    assert str(row.acting_from_tenant_id) == parent_tid


@pytest.mark.asyncio
async def test_actions_in_home_have_null_acting_from(client: AsyncClient) -> None:
    owner = await register_tenant(client, slug="home-audit")
    await client.post(
        "/api/v1/users",
        json={"email": "in-home@home-audit.example.com", "role_codes": ["member"]},
        headers=auth(owner["access_token"]),
    )
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.scalar(
                select(AuditLog).where(AuditLog.action == "user.invite")
                .order_by(AuditLog.created_at.desc())
            )
    assert row is not None
    assert row.acting_from_tenant_id is None
