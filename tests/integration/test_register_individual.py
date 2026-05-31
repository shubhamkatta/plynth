"""B2C signup flow (`POST /auth/register-individual`)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.tenant import Tenant, TenantType
from app.models.user import User
from tests.conftest import auth, product_headers


@pytest.mark.asyncio
async def test_individual_register_creates_tenant_of_one(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "alice@gmail.example.com",
              "password": "S3cretPassword!", "full_name": "Alice Rivers"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"]

    me = await client.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))
    body = me.json()
    assert body["email"] == "alice@gmail.example.com"
    assert body["full_name"] == "Alice Rivers"
    # Owner — same permissions as a company owner.
    assert "*:*" in body["permissions"]


@pytest.mark.asyncio
async def test_individual_tenant_marked_individual(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "bob@gmail.example.com",
              "password": "S3cretPassword!", "full_name": "Bob"},
        headers=product_headers("producta"),
    )
    tok = r.json()["access_token"]
    tenants = await client.get("/api/v1/tenants", headers=auth(tok))
    assert tenants.status_code == 200
    rows = tenants.json()
    assert len(rows) == 1
    assert rows[0]["type"] == "individual"
    assert rows[0]["slug"].startswith("usr-")
    assert rows[0]["is_root"] is True


@pytest.mark.asyncio
async def test_individual_register_falls_back_to_email_local_part(
    client: AsyncClient,
) -> None:
    """No full_name → tenant name derived from email local part."""
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "jane.doe@gmail.example.com",
              "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 201
    tok = r.json()["access_token"]
    tenants = await client.get("/api/v1/tenants", headers=auth(tok))
    assert tenants.json()[0]["name"] == "Jane Doe"


@pytest.mark.asyncio
async def test_individual_register_activates_free_subscription(client: AsyncClient) -> None:
    """B2C signup auto-enrols in the cheapest public plan. For the seeded
    Free plan ($0) the subscription starts ACTIVE with no trial — Free
    never expires. Paid plans would land in TRIAL with trial_end set."""
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "trial@gmail.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    tok = r.json()["access_token"]
    sub = await client.get("/api/v1/subscription", headers=auth(tok))
    assert sub.status_code == 200
    body = sub.json()
    assert body["status"] == "active"
    assert body["has_access"] is True
    assert body["trial_end"] is None


@pytest.mark.asyncio
async def test_individual_register_grants_initial_credits(client: AsyncClient) -> None:
    """Same plan-driven credit grant as a company register."""
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "credits@gmail.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    tok = r.json()["access_token"]
    wallets = await client.get("/api/v1/credits/wallets", headers=auth(tok))
    rows = wallets.json()
    assert any(w["feature_key"] == "credits.ai_completion"
               and float(w["balance"]) == 100.0 for w in rows)


@pytest.mark.asyncio
async def test_individual_can_later_invite_a_user(client: AsyncClient) -> None:
    """Even though the tenant is `individual`, the owner can grow into a
    team. The marker is UI semantics, not a hard cap."""
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "solo@gmail.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    tok = r.json()["access_token"]
    invite = await client.post(
        "/api/v1/users",
        json={"email": "spouse@gmail.example.com", "role_codes": ["member"]},
        headers=auth(tok),
    )
    assert invite.status_code == 201


@pytest.mark.asyncio
async def test_individual_register_requires_product_header(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "x@gmail.example.com", "password": "S3cretPassword!"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_individual_register_rejects_weak_password(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "weak@gmail.example.com", "password": "short"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_classic_register_still_creates_company_tenant(client: AsyncClient) -> None:
    """Backwards compat — default tenant_type is 'company'."""
    r = await client.post(
        "/api/v1/auth/register",
        json={"tenant_name": "Acme Co", "tenant_slug": "acme-co",
              "email": "owner@acme-co.example.com",
              "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 201
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            t = await db.scalar(select(Tenant).where(Tenant.slug == "acme-co"))
    assert t.type == TenantType.COMPANY


@pytest.mark.asyncio
async def test_two_individuals_get_distinct_slugs(client: AsyncClient) -> None:
    """Slug derivation must be collision-resistant across many signups."""
    for i in range(5):
        r = await client.post(
            "/api/v1/auth/register-individual",
            json={"email": f"u{i}@gmail.example.com", "password": "S3cretPassword!"},
            headers=product_headers("producta"),
        )
        assert r.status_code == 201, r.text
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            slugs = (await db.scalars(
                select(Tenant.slug).where(Tenant.type == TenantType.INDIVIDUAL)
            )).all()
    assert len(slugs) == len(set(slugs)) == 5


@pytest.mark.asyncio
async def test_individual_in_one_product_isolated_from_other_product(
    client: AsyncClient,
) -> None:
    """Same email can register as individual in productb without conflict."""
    r1 = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "same@gmail.example.com", "password": "S3cretPassword!"},
        headers=product_headers("producta"),
    )
    r2 = await client.post(
        "/api/v1/auth/register-individual",
        json={"email": "same@gmail.example.com", "password": "S3cretPassword!"},
        headers=product_headers("productb"),
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            users = (await db.scalars(
                select(User).where(User.email == "same@gmail.example.com")
            )).all()
    assert len({u.id for u in users}) == 2
    assert len({u.product_id for u in users}) == 2
