"""Integration tests for POST /api/v1/integrations/google/exchange.

Mocks Google's token endpoint via httpx's MockTransport so we cover
every branch without making real network calls.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_headers

EXCHANGE_PATH = "/api/v1/integrations/google/exchange"
# Test fixtures — formatted so they don't trip GitHub's secret scanner.
# Real Google client IDs look like `<digits>-<alphanum>.apps.googleusercontent.com`;
# real Google client secrets start with `GOCSPX-`. We deliberately avoid both.
GOOGLE_CID = "PLYNTH_TEST_CLIENT_ID_NOT_REAL_xyz"
GOOGLE_SEC = "PLYNTH_TEST_CLIENT_SECRET_NOT_REAL_xyz"


# ---- helpers ---------------------------------------------------------

async def _seed_google_vault(
    client: AsyncClient,
    *,
    product_slug: str = "producta",
    client_id: str = GOOGLE_CID,
    client_secret: str = GOOGLE_SEC,
    id_key: str = "GOOGLE_CLIENT_ID",
    secret_key: str = "GOOGLE_CLIENT_SECRET",
) -> None:
    base = f"/api/v1/admin/products/{product_slug}/env"
    r1 = await client.put(
        f"{base}/{id_key}",
        json={"value": client_id, "is_secret": True},
        headers=platform_admin_headers(),
    )
    assert r1.status_code == 200, r1.text
    r2 = await client.put(
        f"{base}/{secret_key}",
        json={"value": client_secret, "is_secret": True},
        headers=platform_admin_headers(),
    )
    assert r2.status_code == 200, r2.text


async def _issue_token(
    client: AsyncClient,
    *,
    product_slug: str = "producta",
    scopes: list[str] | None = None,
) -> str:
    r = await client.post(
        f"/api/v1/admin/products/{product_slug}/service-tokens",
        json={"name": "test-backend", "scopes": scopes or ["env:read", "google:exchange"]},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _mock_google(handler: Callable[[httpx.Request], httpx.Response]):
    """Patch httpx.AsyncClient inside google_oauth to use a MockTransport
    that calls `handler` instead of the real network."""
    real_async_client = httpx.AsyncClient

    def _factory(*args: Any, **kw: Any) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    return patch("app.services.google_oauth.httpx.AsyncClient", _factory)


def _ok_token_response(body: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    def _handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)
    return _handler


# ---------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authorization_code_exchange(client: AsyncClient) -> None:
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    captured: list[dict[str, str]] = []

    def _handler(req: httpx.Request) -> httpx.Response:
        # Form-encoded body, dict-of-strings.
        form = dict(req.url.params) if req.url.params else dict(
            x.split("=", 1) for x in req.content.decode("utf-8").split("&") if "=" in x
        )
        captured.append(form)
        return httpx.Response(200, json={
            "access_token": "ya29.test_access",
            "expires_in": 3599,
            "refresh_token": "1//test_refresh",
            "scope": "openid email profile",
            "token_type": "Bearer",
        })

    with _mock_google(_handler):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "authorization_code",
                "client_id": GOOGLE_CID,
                "code": "one-time-auth-code-from-google",
                "code_verifier": "a" * 43,
                "redirect_uri": "http://localhost:55001/oauth/callback",
            },
            headers={
                "X-Service-Token": tok,
                "X-Product-Slug": "producta",
                "Idempotency-Key": "11111111-2222-3333-4444-555555555555",
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] == "ya29.test_access"
    assert body["refresh_token"] == "1//test_refresh"
    assert body["expires_in"] == 3599

    # Form sent to Google has client_secret injected server-side.
    import urllib.parse
    raw_form_body = captured[0]
    assert raw_form_body["grant_type"] == "authorization_code"
    assert raw_form_body["client_id"] == GOOGLE_CID
    assert urllib.parse.unquote_plus(raw_form_body["client_secret"]) == GOOGLE_SEC
    assert raw_form_body["code"] == "one-time-auth-code-from-google"
    assert raw_form_body["code_verifier"] == "a" * 43
    assert urllib.parse.unquote_plus(raw_form_body["redirect_uri"]) == "http://localhost:55001/oauth/callback"


@pytest.mark.asyncio
async def test_refresh_token_exchange_no_refresh_in_response(client: AsyncClient) -> None:
    """Google rarely returns a new refresh_token on refresh grant — we
    must NOT synthesize one; absent stays absent."""
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    with _mock_google(_ok_token_response({
        "access_token": "ya29.fresh",
        "expires_in": 3599,
        "scope": "openid",
        "token_type": "Bearer",
    })):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "refresh_token",
                "client_id": GOOGLE_CID,
                "refresh_token": "1//stored_refresh",
            },
            headers={
                "X-Service-Token": tok,
                "X-Product-Slug": "producta",
                "Idempotency-Key": "11111111-2222-3333-4444-555555555555",
            },
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] == "ya29.fresh"
    assert body.get("refresh_token") is None


@pytest.mark.asyncio
async def test_secret_lookup_supports_named_client_pairs(client: AsyncClient) -> None:
    """A product can register multiple Google clients (e.g. a Gmail one).
    Each client_id matches its own *_CLIENT_SECRET."""
    await _seed_google_vault(client)  # default GOOGLE_CLIENT_ID/SECRET
    await _seed_google_vault(
        client,
        client_id="PLYNTH_TEST_GMAIL_CLIENT_ID_NOT_REAL_xyz",
        client_secret="PLYNTH_TEST_GMAIL_CLIENT_SECRET_NOT_REAL_xyz",
        id_key="GOOGLE_GMAIL_CLIENT_ID",
        secret_key="GOOGLE_GMAIL_CLIENT_SECRET",
    )
    tok = await _issue_token(client)

    seen_secrets: list[str] = []

    def _handler(req: httpx.Request) -> httpx.Response:
        import urllib.parse
        form = dict(x.split("=", 1) for x in req.content.decode("utf-8").split("&") if "=" in x)
        seen_secrets.append(urllib.parse.unquote_plus(form["client_secret"]))
        return httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3599})

    with _mock_google(_handler):
        await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "refresh_token",
                "client_id": "PLYNTH_TEST_GMAIL_CLIENT_ID_NOT_REAL_xyz",
                "refresh_token": "x",
            },
            headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                     "Idempotency-Key": "00000000-0000-0000-0000-000000000001"},
        )

    assert seen_secrets == ["PLYNTH_TEST_GMAIL_CLIENT_SECRET_NOT_REAL_xyz"]


# ---------------------------------------------------------------------
# Validation & auth errors
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_code_verifier_422(client: AsyncClient) -> None:
    await _seed_google_vault(client)
    tok = await _issue_token(client)
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "authorization_code",
            "client_id": GOOGLE_CID,
            "code": "one-time-auth-code",
            "redirect_uri": "http://localhost:55001/oauth/callback",
        },
        headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                 "Idempotency-Key": "00000000-0000-0000-0000-000000000002"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_short_code_verifier_422(client: AsyncClient) -> None:
    """PKCE verifier must be 43-128 chars per RFC 7636."""
    await _seed_google_vault(client)
    tok = await _issue_token(client)
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "authorization_code",
            "client_id": GOOGLE_CID,
            "code": "x" * 20,
            "code_verifier": "a" * 10,
            "redirect_uri": "http://localhost:55001/oauth/callback",
        },
        headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                 "Idempotency-Key": "00000000-0000-0000-0000-000000000003"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unknown_client_id_422(client: AsyncClient) -> None:
    await _seed_google_vault(client)
    tok = await _issue_token(client)
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": "PLYNTH_TEST_UNKNOWN_CLIENT_ID_NOT_REAL_xyz",
            "refresh_token": "x",
        },
        headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                 "Idempotency-Key": "00000000-0000-0000-0000-000000000004"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_missing_service_token_401(client: AsyncClient) -> None:
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": GOOGLE_CID,
            "refresh_token": "x",
        },
        headers={"X-Product-Slug": "producta"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_invalid_service_token_401(client: AsyncClient) -> None:
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": GOOGLE_CID,
            "refresh_token": "x",
        },
        headers={"X-Service-Token": "pst_bogus", "X-Product-Slug": "producta"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_scope_403(client: AsyncClient) -> None:
    """Token with env:read only (no google:exchange) → 403."""
    await _seed_google_vault(client)
    tok = await _issue_token(client, scopes=["env:read"])
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": GOOGLE_CID,
            "refresh_token": "x",
        },
        headers={"X-Service-Token": tok, "X-Product-Slug": "producta"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_product_slug_mismatch_403(client: AsyncClient) -> None:
    """A producta token sent with X-Product-Slug=productb → 403."""
    await _seed_google_vault(client)
    tok = await _issue_token(client, product_slug="producta")
    r = await client.post(
        EXCHANGE_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": GOOGLE_CID,
            "refresh_token": "x",
        },
        headers={"X-Service-Token": tok, "X-Product-Slug": "productb"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------
# Google upstream errors
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_invalid_grant_returns_401_with_error_in_message(client: AsyncClient) -> None:
    """Revoked refresh token: Google returns 400 invalid_grant. We pass
    it back as a 401-class envelope with 'google: invalid_grant' in
    message so the mayva client can render 're-auth needed'."""
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked.",
        })

    with _mock_google(_handler):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "refresh_token",
                "client_id": GOOGLE_CID,
                "refresh_token": "revoked-refresh",
            },
            headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                     "Idempotency-Key": "00000000-0000-0000-0000-000000000005"},
        )

    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert "invalid_grant" in body["message"]
    assert body["details"]["google_error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_google_5xx_returns_503(client: AsyncClient) -> None:
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with _mock_google(_handler):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "refresh_token",
                "client_id": GOOGLE_CID,
                "refresh_token": "x",
            },
            headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                     "Idempotency-Key": "00000000-0000-0000-0000-000000000006"},
        )
    assert r.status_code == 503
    assert r.json()["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_google_network_failure_returns_503(client: AsyncClient) -> None:
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    def _handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    with _mock_google(_handler):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "refresh_token",
                "client_id": GOOGLE_CID,
                "refresh_token": "x",
            },
            headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                     "Idempotency-Key": "00000000-0000-0000-0000-000000000007"},
        )
    assert r.status_code == 503


# ---------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_secrets_in_response_envelope_on_error(client: AsyncClient) -> None:
    """Ensure error responses NEVER include the client_secret, the
    refresh_token, the auth code, the code_verifier, or any
    Google-issued token."""
    await _seed_google_vault(client)
    tok = await _issue_token(client)

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with _mock_google(_handler):
        r = await client.post(
            EXCHANGE_PATH,
            json={
                "grant_type": "authorization_code",
                "client_id": GOOGLE_CID,
                "code": "TOPSECRET_CODE_VALUE",
                "code_verifier": "b" * 64,
                "redirect_uri": "http://localhost:55001/oauth/callback",
            },
            headers={"X-Service-Token": tok, "X-Product-Slug": "producta",
                     "Idempotency-Key": "00000000-0000-0000-0000-000000000008"},
        )
    text = json.dumps(r.json())
    assert "TOPSECRET_CODE_VALUE" not in text
    assert GOOGLE_SEC not in text
    assert "b" * 64 not in text
