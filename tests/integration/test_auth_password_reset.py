"""Forgot / reset password flow.

The platform doesn't send transactional email yet; in non-prod
environments the /password/forgot route returns the raw token in the
response body so the flow is testable end-to-end. In production the
token is omitted (response is the same `ok: true` envelope whether the
email exists or not — no enumeration leak).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import product_headers, register_tenant


@pytest.mark.asyncio
async def test_forgot_password_returns_token_in_dev(client: AsyncClient) -> None:
    await register_tenant(client, slug="resetco", email="alice@reset.example.com")

    r = await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "alice@reset.example.com"},
        headers=product_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["reset_token"] and len(body["reset_token"]) >= 16
    assert body["expires_at"] is not None


@pytest.mark.asyncio
async def test_forgot_password_no_leak_for_unknown_email(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "ghost@nowhere.example.com"},
        headers=product_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    # Same envelope, no token — caller can't distinguish from existing
    # email beyond a timing side-channel.
    assert body["ok"] is True
    assert body["reset_token"] is None


@pytest.mark.asyncio
async def test_reset_password_round_trip(client: AsyncClient) -> None:
    await register_tenant(client, slug="roundtrip", email="bob@round.example.com")

    forgot = await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "bob@round.example.com"},
        headers=product_headers(),
    )
    token = forgot.json()["reset_token"]

    # Consume it to set a new password.
    r = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "NewBobPassword!23"},
    )
    assert r.status_code == 204, r.text

    # New password works.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@round.example.com", "password": "NewBobPassword!23"},
        headers=product_headers(),
    )
    assert ok.status_code == 200

    # Old password (the conftest default) doesn't.
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@round.example.com", "password": "S3cretPassword!"},
        headers=product_headers(),
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_reset_password_token_is_single_use(client: AsyncClient) -> None:
    await register_tenant(client, slug="onceonly", email="c@once.example.com")
    token = (await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "c@once.example.com"},
        headers=product_headers(),
    )).json()["reset_token"]

    first = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "FirstPass!2345"},
    )
    assert first.status_code == 204

    second = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "SecondPass!23456"},
    )
    assert second.status_code == 401
    assert "already used" in second.json()["message"]


@pytest.mark.asyncio
async def test_reset_password_invalid_token_404(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": "a" * 64, "new_password": "WhateverPass!"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reset_password_revokes_existing_refresh_tokens(client: AsyncClient) -> None:
    """After a reset, every refresh token must be revoked so previous
    sessions can't keep minting access tokens with the old credential."""
    await register_tenant(client, slug="revokers", email="d@rev.example.com")

    # Get a refresh token via login.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "d@rev.example.com", "password": "S3cretPassword!"},
        headers=product_headers(),
    )
    refresh_token = login.json()["refresh_token"]

    # Reset password.
    token = (await client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "d@rev.example.com"},
        headers=product_headers(),
    )).json()["reset_token"]
    r = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": "PostResetPass!1"},
    )
    assert r.status_code == 204

    # Old refresh is dead.
    bad = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert bad.status_code == 401
