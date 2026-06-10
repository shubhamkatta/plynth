"""Integration tests for the per-product env-vars vault + service tokens.

Covers admin CRUD, reveal audit, service token issuance, runtime
``/env`` fetch with scope enforcement, and cross-product isolation.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_headers

ADMIN_ENV = "/api/v1/admin/products/producta/env"
ADMIN_TOKENS = "/api/v1/admin/products/producta/service-tokens"
ADMIN_B_ENV = "/api/v1/admin/products/productb/env"


# ---------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_and_list_env_var_secret(client: AsyncClient) -> None:
    r = await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "sk_live_secret_xyz", "is_secret": True,
              "description": "Stripe live key"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "STRIPE_LIVE_KEY"
    assert body["is_secret"] is True
    assert body["description"] == "Stripe live key"
    # List never includes the plaintext for secrets.
    assert "value" not in body or body["value"] is None
    assert body["preview"] == "sk_l…_xyz"  # first 4 + … + last 4 of "sk_live_secret_xyz"

    listing = await client.get(ADMIN_ENV, headers=platform_admin_headers())
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["preview"] == "sk_l…_xyz"


@pytest.mark.asyncio
async def test_non_secret_value_listed_in_plaintext(client: AsyncClient) -> None:
    r = await client.put(
        f"{ADMIN_ENV}/PUBLIC_API_HOST",
        json={"value": "https://api.example.com", "is_secret": False},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_secret"] is False
    assert body["value"] == "https://api.example.com"
    assert body["preview"] is None


@pytest.mark.asyncio
async def test_reveal_requires_reveal_param_and_reason(client: AsyncClient) -> None:
    await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "sk_live_secret_xyz"},
        headers=platform_admin_headers(),
    )

    # without ?reveal → 422
    r = await client.get(f"{ADMIN_ENV}/STRIPE_LIVE_KEY", headers=platform_admin_headers())
    assert r.status_code == 422

    # ?reveal=true but no reason → 422
    r = await client.get(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY?reveal=true",
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422

    # ?reveal=true&reason=... → 200 + plaintext
    r = await client.get(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY?reveal=true&reason=rotating%20to%20new%20key",
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200
    assert r.json()["value"] == "sk_live_secret_xyz"


@pytest.mark.asyncio
async def test_patch_metadata_does_not_rotate(client: AsyncClient) -> None:
    r1 = await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "sk_live_xxx", "description": "first"},
        headers=platform_admin_headers(),
    )
    first_rotated = r1.json()["last_rotated_at"]

    r2 = await client.patch(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"description": "updated"},
        headers=platform_admin_headers(),
    )
    assert r2.status_code == 200
    assert r2.json()["description"] == "updated"
    assert r2.json()["last_rotated_at"] == first_rotated


@pytest.mark.asyncio
async def test_delete_env_var(client: AsyncClient) -> None:
    await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "sk_live_xxx"},
        headers=platform_admin_headers(),
    )
    r = await client.delete(f"{ADMIN_ENV}/STRIPE_LIVE_KEY", headers=platform_admin_headers())
    assert r.status_code == 204

    listing = await client.get(ADMIN_ENV, headers=platform_admin_headers())
    assert listing.json() == []


@pytest.mark.asyncio
async def test_invalid_key_pattern_rejected(client: AsyncClient) -> None:
    r = await client.put(
        f"{ADMIN_ENV}/lower_case",
        json={"value": "x"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_extra_fields_rejected(client: AsyncClient) -> None:
    r = await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "x", "unknown_field": "boom"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422
    assert "extra_forbidden" in r.text


# ---------------------------------------------------------------------
# Server-only key filter (GOOGLE_*_CLIENT_SECRET → hidden from /env)
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_server_only_key_excluded_from_runtime_env(client: AsyncClient) -> None:
    """Step 2 of the OAuth-exchange cutover: GOOGLE_CLIENT_SECRET stays in
    the vault for the platform's use, but `/env` does NOT return it."""
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_CLIENT_ID",
        json={"value": "PLYNTH_TEST_CID_xyz", "is_secret": True},
        headers=platform_admin_headers(),
    )
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_CLIENT_SECRET",
        json={"value": "PLYNTH_TEST_SECRET_NOT_REAL_xyz", "is_secret": True},
        headers=platform_admin_headers(),
    )
    issued = (await client.post(
        ADMIN_TOKENS, json={"name": "x"}, headers=platform_admin_headers(),
    )).json()
    r = await client.get(
        "/api/v1/env", headers={"X-Service-Token": issued["token"]},
    )
    assert r.status_code == 200
    env = r.json()
    assert "GOOGLE_CLIENT_ID" in env  # public id stays
    assert "GOOGLE_CLIENT_SECRET" not in env  # server-only filtered


@pytest.mark.asyncio
async def test_gmail_client_secret_also_server_only(client: AsyncClient) -> None:
    """The pattern matches any GOOGLE_<group>_CLIENT_SECRET, not just the bare one."""
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_GMAIL_CLIENT_ID",
        json={"value": "PLYNTH_TEST_GMAIL_CID_xyz", "is_secret": True},
        headers=platform_admin_headers(),
    )
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_GMAIL_CLIENT_SECRET",
        json={"value": "PLYNTH_TEST_GMAIL_SECRET_xyz", "is_secret": True},
        headers=platform_admin_headers(),
    )
    issued = (await client.post(
        ADMIN_TOKENS, json={"name": "x"}, headers=platform_admin_headers(),
    )).json()
    env = (await client.get(
        "/api/v1/env", headers={"X-Service-Token": issued["token"]},
    )).json()
    assert "GOOGLE_GMAIL_CLIENT_ID" in env
    assert "GOOGLE_GMAIL_CLIENT_SECRET" not in env


@pytest.mark.asyncio
async def test_admin_list_marks_server_only_keys(client: AsyncClient) -> None:
    """Operators need to see at a glance which keys are server-only."""
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_CLIENT_SECRET",
        json={"value": "PLYNTH_TEST_NOT_REAL", "is_secret": True},
        headers=platform_admin_headers(),
    )
    await client.put(
        f"{ADMIN_ENV}/REGULAR_API_KEY",
        json={"value": "regular_key", "is_secret": True},
        headers=platform_admin_headers(),
    )
    listing = (await client.get(ADMIN_ENV, headers=platform_admin_headers())).json()
    rows = {row["key"]: row for row in listing}
    assert rows["GOOGLE_CLIENT_SECRET"]["is_server_only"] is True
    assert rows["REGULAR_API_KEY"]["is_server_only"] is False


@pytest.mark.asyncio
async def test_admin_can_still_reveal_server_only_key(client: AsyncClient) -> None:
    """Server-only filter is /env-only — admin reveal path still works."""
    await client.put(
        f"{ADMIN_ENV}/GOOGLE_CLIENT_SECRET",
        json={"value": "PLYNTH_TEST_REVEAL_xyz", "is_secret": True},
        headers=platform_admin_headers(),
    )
    r = await client.get(
        f"{ADMIN_ENV}/GOOGLE_CLIENT_SECRET?reveal=true&reason=rotation%20test",
        headers=platform_admin_headers(),
    )
    assert r.status_code == 200
    assert r.json()["value"] == "PLYNTH_TEST_REVEAL_xyz"


# ---------------------------------------------------------------------
# Service tokens + product fetch
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_issue_token_returns_secret_once(client: AsyncClient) -> None:
    r = await client.post(
        ADMIN_TOKENS,
        json={"name": "producta-prod-backend"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "producta-prod-backend"
    assert body["scopes"] == ["env:read"]
    assert body["token"].startswith("pst_")
    assert len(body["token"]) == 4 + 32  # prefix + 32 hex chars

    # Subsequent list never returns the plaintext.
    listing = await client.get(ADMIN_TOKENS, headers=platform_admin_headers())
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert "token" not in items[0]


@pytest.mark.asyncio
async def test_product_fetch_returns_decrypted_env(client: AsyncClient) -> None:
    # Seed two vars (one secret, one not) on producta.
    await client.put(
        f"{ADMIN_ENV}/STRIPE_LIVE_KEY",
        json={"value": "sk_live_xxx"},
        headers=platform_admin_headers(),
    )
    await client.put(
        f"{ADMIN_ENV}/PUBLIC_API_HOST",
        json={"value": "https://api.example.com", "is_secret": False},
        headers=platform_admin_headers(),
    )
    # Issue a service token for producta.
    issued = (await client.post(
        ADMIN_TOKENS,
        json={"name": "backend"},
        headers=platform_admin_headers(),
    )).json()
    token = issued["token"]

    # Fetch via /env with the token.
    r = await client.get(
        "/api/v1/env",
        headers={"X-Service-Token": token},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "STRIPE_LIVE_KEY": "sk_live_xxx",
        "PUBLIC_API_HOST": "https://api.example.com",
    }


@pytest.mark.asyncio
async def test_missing_service_token_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/env")
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_revoked_service_token_is_401(client: AsyncClient) -> None:
    issued = (await client.post(
        ADMIN_TOKENS, json={"name": "x"}, headers=platform_admin_headers(),
    )).json()
    token, token_id = issued["token"], issued["id"]
    # works first
    assert (await client.get("/api/v1/env",
            headers={"X-Service-Token": token})).status_code == 200
    # revoke
    r = await client.delete(f"{ADMIN_TOKENS}/{token_id}", headers=platform_admin_headers())
    assert r.status_code == 204
    # fails after
    r = await client.get("/api/v1/env", headers={"X-Service-Token": token})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cross_product_isolation(client: AsyncClient) -> None:
    """A producta token cannot read productb's env even with productb's slug."""
    await client.put(
        f"{ADMIN_B_ENV}/SECRET",
        json={"value": "productb_secret"},
        headers=platform_admin_headers(),
    )
    issued_a = (await client.post(
        ADMIN_TOKENS, json={"name": "a"}, headers=platform_admin_headers(),
    )).json()

    # With the producta token + productb's slug header → 403 (slug mismatch).
    r = await client.get(
        "/api/v1/env",
        headers={
            "X-Service-Token": issued_a["token"],
            "X-Product-Slug": "productb",
        },
    )
    assert r.status_code == 403

    # No slug header → service token implies producta → returns producta's env
    # (which is empty in this test — no env vars set on producta).
    r = await client.get("/api/v1/env", headers={"X-Service-Token": issued_a["token"]})
    assert r.status_code == 200
    assert r.json() == {}


@pytest.mark.asyncio
async def test_admin_calls_require_platform_admin_token(client: AsyncClient) -> None:
    # Without admin token → 401
    r = await client.put(
        f"{ADMIN_ENV}/X",
        json={"value": "y"},
        headers={"X-Product-Slug": "producta"},  # only product slug, no admin token
    )
    assert r.status_code == 401

    r = await client.post(
        ADMIN_TOKENS, json={"name": "x"},
        headers={"X-Product-Slug": "producta"},
    )
    assert r.status_code == 401
