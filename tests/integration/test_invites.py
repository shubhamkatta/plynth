"""Invite system: create (tenant-admin + platform-admin prospect), preview,
accept (join_tenant / new_tenant), single-use, expiry, isolation, hosted page."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.invite import InviteToken
from tests.conftest import auth, register_tenant

PW = "a-long-enough-password-1"
ADMIN = {"X-Platform-Admin-Token": "test-platform-admin-token"}


def _token(link: str) -> str:
    return link.split("token=", 1)[1]


async def _admin_invite(client: AsyncClient, slug: str, email: str, **extra) -> dict:
    r = await client.post(
        f"/api/v1/admin/products/{slug}/invites",
        json={"email": email, **extra}, headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_prospect_invite_creates_own_tenant_and_is_single_use(client: AsyncClient) -> None:
    inv = await _admin_invite(client, "producta", "prospect@example.com",
                              full_name="Pat Prospect", plan_code="practice")
    assert inv["kind"] == "new_tenant" and inv["link"]
    token = _token(inv["link"])

    pv = await client.post("/api/v1/auth/invites/preview", json={"token": token})
    assert pv.status_code == 200
    assert pv.json()["email"] == "prospect@example.com"
    assert pv.json()["plan_code"] == "practice"

    r = await client.post("/api/v1/auth/invites/accept",
                          json={"token": token, "password": PW})
    assert r.status_code == 201, r.text
    me = await client.get("/api/v1/auth/me", headers=auth(r.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "prospect@example.com"

    again = await client.post("/api/v1/auth/invites/accept",
                              json={"token": token, "password": PW})
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_invalid_expired_and_revoked_tokens_look_identical(client: AsyncClient) -> None:
    inv = await _admin_invite(client, "producta", "expired@example.com")
    token = _token(inv["link"])
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.scalar(
                select(InviteToken).where(InviteToken.email == "expired@example.com")
            )
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    unknown = await client.post("/api/v1/auth/invites/preview", json={"token": "x" * 43})
    expired = await client.post("/api/v1/auth/invites/preview", json={"token": token})
    assert unknown.status_code == expired.status_code == 404
    assert unknown.json()["message"] == expired.json()["message"]

    first = await _admin_invite(client, "producta", "again@example.com")
    second = await _admin_invite(client, "producta", "again@example.com")
    old = await client.post("/api/v1/auth/invites/preview", json={"token": _token(first["link"])})
    new = await client.post("/api/v1/auth/invites/preview", json={"token": _token(second["link"])})
    assert old.status_code == 404 and new.status_code == 200


@pytest.mark.asyncio
async def test_tenant_admin_invite_joins_callers_tenant(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    h = auth(tok["access_token"])
    r = await client.post(
        "/api/v1/users/invites",
        json={"email": "mate@acme.example.com", "role_codes": ["member"]}, headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "join_tenant"
    acc = await client.post("/api/v1/auth/invites/accept",
                            json={"token": _token(r.json()["link"]), "password": PW})
    assert acc.status_code == 201, acc.text

    users = await client.get("/api/v1/users", headers=h)
    assert "mate@acme.example.com" in {u["email"] for u in users.json()}

    dup = await client.post("/api/v1/users/invites",
                            json={"email": "mate@acme.example.com"}, headers=h)
    assert dup.status_code == 409
    bad = await client.post("/api/v1/users/invites",
                            json={"email": "x@acme.example.com", "role_codes": ["nope"]}, headers=h)
    assert bad.status_code == 404


@pytest.mark.asyncio
async def test_invite_endpoints_are_guarded(client: AsyncClient) -> None:
    no_auth = await client.post("/api/v1/users/invites", json={"email": "a@b.example.com"})
    assert no_auth.status_code in (401, 403)
    no_admin = await client.post("/api/v1/admin/products/producta/invites",
                                 json={"email": "a@b.example.com"})
    assert no_admin.status_code in (401, 403)


@pytest.mark.asyncio
async def test_invited_account_is_product_isolated(client: AsyncClient) -> None:
    inv = await _admin_invite(client, "producta", "iso@example.com")
    r = await client.post("/api/v1/auth/invites/accept",
                          json={"token": _token(inv["link"]), "password": PW})
    assert r.status_code == 201
    b_login = await client.post(
        "/api/v1/auth/login", json={"email": "iso@example.com", "password": PW},
        headers={"X-Product-Slug": "productb"},
    )
    assert b_login.status_code == 401


@pytest.mark.asyncio
async def test_hosted_invite_page_is_static_and_hardened(client: AsyncClient) -> None:
    r = await client.get("/invite?token=abc")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "abc" not in r.text
