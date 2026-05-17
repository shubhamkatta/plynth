"""Auth: register, login, refresh, logout, password change, /me."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, product_headers, register_tenant


@pytest.mark.asyncio
async def test_register_creates_owner_with_full_permissions(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "owner@acme.example.com"
    assert "*:*" in body["permissions"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_slug(client: AsyncClient) -> None:
    await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": "Acme 2", "tenant_slug": "acme",
            "email": "second@acme.example.com", "password": "S3cretPassword!",
        },
        headers=product_headers("producta"),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": "Acme", "tenant_slug": "weakpw",
            "email": "u@weakpw.example.com", "password": "short",
        },
        headers=product_headers("producta"),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_bad_slug(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "tenant_name": "X", "tenant_slug": "Has Spaces!",
            "email": "u@badslug.example.com", "password": "S3cretPassword!",
        },
        headers=product_headers("producta"),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_without_product_header_is_422(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/register", json={
        "tenant_name": "X", "tenant_slug": "noheader",
        "email": "x@noheader.example.com", "password": "S3cretPassword!",
    })
    assert r.status_code == 422
    assert "X-Product-Slug" in r.text


@pytest.mark.asyncio
async def test_register_unknown_product_is_422(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"tenant_name": "X", "tenant_slug": "x",
              "email": "x@x.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "no-such-product"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_with_correct_credentials(client: AsyncClient) -> None:
    await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "S3cretPassword!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 200
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_login_with_wrong_password(client: AsyncClient) -> None:
    await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "NopeNopeNope1!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@nowhere.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me", headers=auth("not-a-real-jwt"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_tokens(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["access_token"] != tok["access_token"]
    assert new["refresh_token"] != tok["refresh_token"]
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tok["refresh_token"], "all_sessions": False},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 204
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_sessions(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "S3cretPassword!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    tok2 = r2.json()
    await client.post(
        "/api/v1/auth/logout", json={"all_sessions": True},
        headers=auth(tok2["access_token"]),
    )
    for rt in [tok["refresh_token"], tok2["refresh_token"]]:
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_then_login_with_new(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/password",
        json={"current_password": "S3cretPassword!", "new_password": "BrandNewPwd99!"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 204
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "S3cretPassword!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    assert bad.status_code == 401
    good = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "BrandNewPwd99!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    assert good.status_code == 200


@pytest.mark.asyncio
async def test_change_password_with_wrong_current(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/auth/password",
        json={"current_password": "WrongOne123!", "new_password": "BrandNewPwd99!"},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_finds_correct_tenant_when_slug_omitted(client: AsyncClient) -> None:
    """If only one tenant has that email in the product, login should succeed
    without the tenant_slug."""
    await register_tenant(client, slug="acme", email="solo@acme.example.com")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "solo@acme.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 200
