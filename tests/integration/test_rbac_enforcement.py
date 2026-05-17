"""RBAC enforcement: members get 403 on owner-only endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.security import hash_password
from app.core.tenant import bypass_product, bypass_tenant
from app.models.user import User
from tests.conftest import auth, product_headers, register_tenant


async def _member_login_token(client: AsyncClient, owner_token: str, email: str) -> str:
    """Invite a user, then manually set their password so we can log them in."""
    invited = await client.post(
        "/api/v1/users",
        json={"email": email, "role_codes": ["member"]},
        headers=auth(owner_token),
    )
    uid = invited.json()["id"]
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            u = await db.get(User, uid)
            u.password_hash = hash_password("MemberPwd99!")
            u.is_verified = True
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "MemberPwd99!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_member_cannot_invite_users(client: AsyncClient) -> None:
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    r = await client.post(
        "/api/v1/users",
        json={"email": "blocked@acme.example.com", "role_codes": ["member"]},
        headers=auth(member),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_create_role(client: AsyncClient) -> None:
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    r = await client.post(
        "/api/v1/roles",
        json={"name": "shadow", "permission_codes": []},
        headers=auth(member),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_purchase_plan(client: AsyncClient) -> None:
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    r = await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "pro"},
        headers=auth(member),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_member_can_consume_credits(client: AsyncClient) -> None:
    """The member role has `credits:consume`."""
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    r = await client.post(
        "/api/v1/credits/consume",
        json={"feature_key": "credits.ai_completion", "amount": "1"},
        headers=auth(member),
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_member_cannot_grant_credits(client: AsyncClient) -> None:
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    r = await client.post(
        "/api/v1/credits/grant",
        json={"feature_key": "credits.ai_completion", "amount": "1000"},
        headers=auth(member),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_inactive_user_cannot_login(client: AsyncClient) -> None:
    """After deactivation, the user's token stops working and re-login is denied."""
    owner = await register_tenant(client, slug="acme")
    member = await _member_login_token(client, owner["access_token"], "m@acme.example.com")
    # Owner deactivates the member.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            u = await db.scalar(select(User).where(User.email == "m@acme.example.com"))
            u.is_active = False
    # Old token rejected.
    r = await client.get("/api/v1/auth/me", headers=auth(member))
    assert r.status_code == 401
    # Re-login denied.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "m@acme.example.com", "password": "MemberPwd99!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 401
