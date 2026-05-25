"""Per-product refresh-token TTL.

Reads `Product.settings.auth.refresh_ttl_days` if present, falls back to
the platform-wide `JWT_REFRESH_TTL_SECONDS` (30 days). Set via
`PATCH /api/v1/admin/products/{slug}` with a partial `settings` patch
that deep-merges into the existing JSONB.
"""

from datetime import UTC, datetime

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import platform_admin_headers, product_headers, register_tenant


def _exp_of(token: str) -> datetime:
    """Decode without verifying signature/expiry — we only want the `exp`
    claim to assert how long the token is valid for."""
    payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
    return datetime.fromtimestamp(payload["exp"], tz=UTC)


@pytest.mark.asyncio
async def test_default_refresh_ttl_matches_platform_default(client: AsyncClient) -> None:
    """No per-product override → platform-wide JWT_REFRESH_TTL_SECONDS
    applies (30 days by default; test env may differ)."""
    await register_tenant(client, slug="ttl-default", email="u@ttl.example.com")

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "u@ttl.example.com", "password": "S3cretPassword!"},
        headers=product_headers(),
    )
    assert r.status_code == 200
    issued_at = datetime.now(UTC)
    exp = _exp_of(r.json()["refresh_token"])
    delta = (exp - issued_at).total_seconds()
    # Within 10s slack for test timing.
    assert abs(delta - settings.jwt_refresh_ttl_seconds) < 10


@pytest.mark.asyncio
async def test_patch_product_sets_refresh_ttl_days(client: AsyncClient) -> None:
    """Admin sets a 7-day TTL on a product; subsequent logins get a
    refresh token whose `exp` claim is ~7 days out."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Short TTL", "slug": "short-ttl"},
        headers=platform_admin_headers(),
    )
    r = await client.patch(
        "/api/v1/admin/products/short-ttl",
        json={"settings": {"auth": {"refresh_ttl_days": 7}}},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["auth"]["refresh_ttl_days"] == 7

    # Register a user + log in inside this product.
    await register_tenant(client, slug="ten", email="u@short.example.com",
                          product_slug="short-ttl")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "u@short.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "short-ttl"},
    )
    assert r.status_code == 200
    issued_at = datetime.now(UTC)
    exp = _exp_of(r.json()["refresh_token"])
    days = (exp - issued_at).total_seconds() / 86400
    assert 6.99 < days < 7.01


@pytest.mark.asyncio
async def test_patch_settings_deep_merges(client: AsyncClient) -> None:
    """Partial patches must NOT wipe unrelated settings keys."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Merge Co", "slug": "merge-co",
              "settings": {"features": {"google_auto_provision": True}}},
        headers=platform_admin_headers(),
    )
    # Patch only auth — features.* must survive.
    r = await client.patch(
        "/api/v1/admin/products/merge-co",
        json={"settings": {"auth": {"refresh_ttl_days": 14}}},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["auth"]["refresh_ttl_days"] == 14
    assert s["features"]["google_auto_provision"] is True


@pytest.mark.asyncio
async def test_patch_rejects_unknown_product(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/v1/admin/products/does-not-exist",
        json={"settings": {"auth": {"refresh_ttl_days": 7}}},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_rejects_empty_body(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/v1/admin/products/producta",
        json={},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_ttl_falls_back_to_default(client: AsyncClient) -> None:
    """Out-of-range or non-int values are ignored (bounded [1, 365] days).
    Prevents typos from creating tokens that never expire / expire instantly."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Bad TTL", "slug": "bad-ttl"},
        headers=platform_admin_headers(),
    )
    # 0 days is out of range — must fall back to platform default.
    r = await client.patch(
        "/api/v1/admin/products/bad-ttl",
        json={"settings": {"auth": {"refresh_ttl_days": 0}}},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200  # patch itself is accepted (we just store it)

    await register_tenant(client, slug="ten", email="u@bad.example.com",
                          product_slug="bad-ttl")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "u@bad.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "bad-ttl"},
    )
    exp = _exp_of(r.json()["refresh_token"])
    delta = (exp - datetime.now(UTC)).total_seconds()
    # Fell back to platform default, not 0 days.
    assert abs(delta - settings.jwt_refresh_ttl_seconds) < 10


@pytest.mark.asyncio
async def test_refresh_rotates_with_current_product_ttl(client: AsyncClient) -> None:
    """If admin shortens the TTL after a user has logged in, the next
    /refresh rotation issues a token bound to the NEW (shorter) TTL —
    not the old one carried forward."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Rotate Co", "slug": "rotate-co"},
        headers=platform_admin_headers(),
    )
    await register_tenant(client, slug="ten", email="u@rot.example.com",
                          product_slug="rotate-co")

    # Initial login uses platform default.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "u@rot.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "rotate-co"},
    )
    old_refresh = login.json()["refresh_token"]
    old_exp     = _exp_of(old_refresh)
    assert abs((old_exp - datetime.now(UTC)).total_seconds() - settings.jwt_refresh_ttl_seconds) < 10

    # Admin shortens to 3 days.
    await client.patch(
        "/api/v1/admin/products/rotate-co",
        json={"settings": {"auth": {"refresh_ttl_days": 3}}},
        headers=platform_admin_headers(),
    )

    # Refresh — new token should reflect the new 3-day TTL.
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert r.status_code == 200
    new_exp = _exp_of(r.json()["refresh_token"])
    days = (new_exp - datetime.now(UTC)).total_seconds() / 86400
    assert 2.99 < days < 3.01
