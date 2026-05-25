"""Google OAuth login flow.

Two paths:
- Existing user with verified Google email → log in, issue platform JWTs.
- No matching user + product opts in to `google_auto_provision` →
  auto-create a B2C-style tenant + user, then log in.

Google's HTTP endpoints are mocked with respx — no network in tests.
"""


import pytest
import respx
from httpx import AsyncClient, Response

from app.core.config import settings
from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.product import Product
from tests.conftest import product_headers, register_tenant

GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def mock_google_ok(mock: respx.MockRouter, *, email: str, verified: bool = True,
                   name: str = "Test User", sub: str = "g-12345") -> None:
    mock.post(GOOGLE_TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
    )
    mock.get(GOOGLE_USERINFO_URL).mock(
        return_value=Response(200, json={
            "sub":            sub,
            "email":          email,
            "email_verified": verified,
            "name":           name,
        })
    )


@pytest.fixture(autouse=True)
def _google_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file needs Google creds configured."""
    monkeypatch.setattr(settings, "google_client_id",     "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


@pytest.mark.asyncio
async def test_google_login_existing_user(client: AsyncClient) -> None:
    await register_tenant(client, slug="gco", email="alice@gco.example.com")

    with respx.mock(assert_all_called=True) as mock:
        mock_google_ok(mock, email="alice@gco.example.com")
        r = await client.post(
            "/api/v1/auth/google",
            json={"code": "auth-code-abc", "redirect_uri": "https://gco.app/oauth/callback"},
            headers=product_headers(),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]


@pytest.mark.asyncio
async def test_google_login_unverified_email_rejected(client: AsyncClient) -> None:
    await register_tenant(client, slug="gco2", email="bob@gco2.example.com")

    with respx.mock(assert_all_called=True) as mock:
        mock_google_ok(mock, email="bob@gco2.example.com", verified=False)
        r = await client.post(
            "/api/v1/auth/google",
            json={"code": "auth-code-xyz", "redirect_uri": "https://gco2.app/cb"},
            headers=product_headers(),
        )
    assert r.status_code == 401
    assert "verified email" in r.json()["message"]


@pytest.mark.asyncio
async def test_google_login_unknown_user_no_autoprovision_rejected(
    client: AsyncClient,
) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock_google_ok(mock, email="ghost@somewhere.example.com")
        r = await client.post(
            "/api/v1/auth/google",
            json={"code": "auth-code-xyz", "redirect_uri": "https://producta.app/cb"},
            headers=product_headers(),  # producta has no auto-provision flag
        )
    assert r.status_code == 401
    assert "no account" in r.json()["message"]


@pytest.mark.asyncio
async def test_google_login_auto_provisions_when_product_opts_in(
    client: AsyncClient,
) -> None:
    # Flip the per-product flag on `producta`.
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                __import__("sqlalchemy", fromlist=["select"]).select(Product)
                .where(Product.slug == "producta")
            )
            product.settings = {
                **(product.settings or {}),
                "features": {"google_auto_provision": True},
            }

    with respx.mock(assert_all_called=True) as mock:
        mock_google_ok(mock, email="new@new.example.com", name="New Person")
        r = await client.post(
            "/api/v1/auth/google",
            json={"code": "auth-code-xyz", "redirect_uri": "https://producta.app/cb"},
            headers=product_headers(),
        )
    assert r.status_code == 200, r.text
    # Now /me works with the issued access token.
    access = r.json()["access_token"]
    me = await client.get(
        "/api/v1/auth/me",
        headers={**product_headers(), "Authorization": f"Bearer {access}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "new@new.example.com"


@pytest.mark.asyncio
async def test_google_login_when_unconfigured_returns_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")

    r = await client.post(
        "/api/v1/auth/google",
        json={"code": "x" * 20, "redirect_uri": "https://x.example.com/cb"},
        headers=product_headers(),
    )
    assert r.status_code == 401
    assert "not configured" in r.json()["message"]


@pytest.mark.asyncio
async def test_google_login_token_exchange_failure(client: AsyncClient) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(GOOGLE_TOKEN_URL).mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        r = await client.post(
            "/api/v1/auth/google",
            json={"code": "bad-code-12345", "redirect_uri": "https://producta.app/cb"},
            headers=product_headers(),
        )
    assert r.status_code == 401
    assert "exchange failed" in r.json()["message"]
