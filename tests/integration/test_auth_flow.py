"""Smoke test: register → login → me → logout. Requires running Postgres+Redis."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, product_headers


@pytest.mark.asyncio
async def test_register_login_me(client: AsyncClient) -> None:
    payload = {
        "tenant_name": "Acme Inc",
        "tenant_slug": "acme",
        "email": "alice@acme.example.com",
        "password": "S3cretPassword!",
        "full_name": "Alice",
    }
    r = await client.post(
        "/api/v1/auth/register", json=payload, headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"]

    me = await client.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "alice@acme.example.com"
    assert "*:*" in body["permissions"]
    assert body["product_id"]


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient) -> None:
    """A user from tenant A must not see tenant B's users."""
    for slug, email in [("alpha", "a@alpha.example.com"), ("beta", "b@beta.example.com")]:
        await client.post(
            "/api/v1/auth/register",
            json={
                "tenant_name": slug.title(),
                "tenant_slug": slug,
                "email": email,
                "password": "S3cretPassword!",
            },
            headers=product_headers("producta"),
        )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "a@alpha.example.com", "password": "S3cretPassword!", "tenant_slug": "alpha"},
        headers=product_headers("producta"),
    )
    token = r.json()["access_token"]
    users = await client.get("/api/v1/users", headers=auth(token))
    assert users.status_code == 200
    emails = {u["email"] for u in users.json()}
    assert emails == {"a@alpha.example.com"}
