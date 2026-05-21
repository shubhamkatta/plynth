"""Platform-admin token authenticates as a god user on tenant-scoped routes.

The PLATFORM_ADMIN_TOKEN is meant to give a true super-user across every
product, not just /admin/products. These tests cover that contract:
- Admin token + X-Product-Slug → all RBAC-gated routes accept the call.
- Admin token without X-Product-Slug → 422 (which product to operate on?).
- Wrong / missing admin token + no JWT → 401 (existing behavior).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import platform_admin_headers, product_headers


def admin_scope(slug: str = "producta") -> dict[str, str]:
    return {**platform_admin_headers(), **product_headers(slug)}


@pytest.mark.asyncio
async def test_admin_token_lists_tenants_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=admin_scope())
    assert r.status_code == 200, r.text
    # At minimum the seeded root tenant for producta should be visible.
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_admin_token_lists_users_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_roles_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/roles", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_plans_in_product(client: AsyncClient) -> None:
    r = await client.get("/api/v1/plans", headers=admin_scope())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_token_lists_permissions(client: AsyncClient) -> None:
    # /roles/permissions is RBAC-gated; admin should pass.
    r = await client.get("/api/v1/roles/permissions", headers=admin_scope())
    assert r.status_code == 200, r.text
    assert "*:*" in r.json()


@pytest.mark.asyncio
async def test_admin_token_without_product_header_is_422(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=platform_admin_headers())
    # ValidationFailed → 422 (the dep raises before route runs).
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_no_token_no_jwt_is_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tenants", headers=product_headers())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_admin_token_falls_through_and_401s(client: AsyncClient) -> None:
    # Wrong token isn't accepted as god-mode; without a JWT it's "missing bearer".
    headers = {**product_headers(), "X-Platform-Admin-Token": "wrong"}
    r = await client.get("/api/v1/tenants", headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_bootstrap_root_tenant_in_empty_product(client: AsyncClient) -> None:
    """Empty product has no tenants — admin must be able to create the first
    root tenant directly (parent_id implicitly None)."""
    # Create a fresh product via admin so it's guaranteed empty.
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "Fresh", "slug": "fresh-bootstrap"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text

    # Admin lists tenants in the empty product → []
    r = await client.get(
        "/api/v1/tenants",
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 200
    assert r.json() == []

    # Admin creates the first root tenant — no parent_id.
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Root Co", "slug": "root-co"},
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "root-co"
    assert body["is_root"] is True
    assert body["parent_id"] is None

    # Now admin can list it.
    r = await client.get(
        "/api/v1/tenants",
        headers={**platform_admin_headers(), "X-Product-Slug": "fresh-bootstrap"},
    )
    assert r.status_code == 200
    assert any(t["slug"] == "root-co" for t in r.json())


@pytest.mark.asyncio
async def test_create_product_seeds_standard_b2b_plans(client: AsyncClient) -> None:
    """Default seed_plans=True + tenant_type=COMPANY → 3 standard B2B plans
    (free, pro, enterprise) appear in /api/v1/plans for the new product."""
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "B2B Co", "slug": "b2b-co"},   # defaults: seed_plans=True, tenant_type=company
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/api/v1/plans",
        headers={**platform_admin_headers(), "X-Product-Slug": "b2b-co"},
    )
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert {"free", "pro", "enterprise"}.issubset(codes)


@pytest.mark.asyncio
async def test_create_product_seeds_standard_b2c_plans(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "B2C App", "slug": "b2c-app", "tenant_type": "individual"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/api/v1/plans",
        headers={**platform_admin_headers(), "X-Product-Slug": "b2c-app"},
    )
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert {"free", "pro", "max"}.issubset(codes)


@pytest.mark.asyncio
async def test_create_product_with_seed_plans_false_skips_seeding(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/admin/products",
        json={"name": "No Seed", "slug": "no-seed", "seed_plans": False},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/api/v1/plans",
        headers={**platform_admin_headers(), "X-Product-Slug": "no-seed"},
    )
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_admin_bootstraps_tenant_with_owner_and_plan(client: AsyncClient) -> None:
    """One call → product + plans + tenant + owner user + trial subscription."""
    # Product with auto-seeded B2B plans.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Bootstrap Co", "slug": "bootstrap-co"},
        headers=platform_admin_headers(),
    )
    # Atomic tenant + owner + sub on "pro" plan.
    r = await client.post(
        "/api/v1/tenants",
        json={
            "name": "Acme",
            "slug": "acme",
            "owner": {
                "email":     "owner@acme.example.com",
                "password":  "S3cretPassword!",
                "full_name": "Alice Owner",
            },
            "plan_code": "pro",
        },
        headers={**platform_admin_headers(), "X-Product-Slug": "bootstrap-co"},
    )
    assert r.status_code == 201, r.text
    tenant = r.json()
    assert tenant["slug"] == "acme"
    assert tenant["is_root"] is True

    # Owner can sign in immediately.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "bootstrap-co"},
    )
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]

    # And the trial subscription exists on the chosen plan.
    r = await client.get(
        "/api/v1/subscription",
        headers={"Authorization": f"Bearer {access}", "X-Product-Slug": "bootstrap-co"},
    )
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["plan_code"] == "pro"
    assert sub["status"] == "trial"


@pytest.mark.asyncio
async def test_admin_patch_tenant_expires_at_enforced_for_users(
    client: AsyncClient,
) -> None:
    """Setting tenant.expires_at in the past denies all user auth in that
    tenant. Admin override (set to null or future) restores access."""
    from datetime import datetime, timedelta, UTC

    # Bootstrap a product + tenant + owner.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Expiry Co", "slug": "expiry-co"},
        headers=platform_admin_headers(),
    )
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Exp", "slug": "exp",
              "owner": {"email": "u@exp.example.com", "password": "S3cretPassword!"},
              "plan_code": "free"},
        headers={**platform_admin_headers(), "X-Product-Slug": "expiry-co"},
    )
    assert r.status_code == 201, r.text
    tenant_id = r.json()["id"]

    # User can sign in now.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "u@exp.example.com", "password": "S3cretPassword!"},
        headers={"X-Product-Slug": "expiry-co"},
    )
    assert r.status_code == 200
    access = r.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {access}", "X-Product-Slug": "expiry-co"}
    assert (await client.get("/api/v1/auth/me", headers=user_headers)).status_code == 200

    # Admin sets expires_at in the past.
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    r = await client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"expires_at": past},
        headers={**platform_admin_headers(), "X-Product-Slug": "expiry-co"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"] is not None

    # User's authenticated calls are denied.
    r = await client.get("/api/v1/auth/me", headers=user_headers)
    assert r.status_code == 403, r.text
    assert "expired" in r.json()["message"]

    # Admin overrides — set expires_at back to null.
    r = await client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"expires_at": None},
        headers={**platform_admin_headers(), "X-Product-Slug": "expiry-co"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"] is None

    # User can authenticate again.
    r = await client.get("/api/v1/auth/me", headers=user_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_invite_user_returns_initial_password(client: AsyncClient) -> None:
    """POST /users returns a one-shot initial_password so the inviter can
    share it out-of-band (no SMTP is wired). When the inviter supplies a
    password, that exact value comes back; otherwise a random one is
    generated server-side."""
    # Bootstrap a product + a root tenant so we have a tenant scope.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Invite Co", "slug": "invite-co"},
        headers=platform_admin_headers(),
    )
    await client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
        headers={**platform_admin_headers(), "X-Product-Slug": "invite-co"},
    )

    # No password supplied → server generates one.
    r = await client.post(
        "/api/v1/users",
        json={"email": "alice@acme.example.com", "role_codes": ["member"]},
        headers={**platform_admin_headers(), "X-Product-Slug": "invite-co"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "alice@acme.example.com"
    generated = body["initial_password"]
    assert isinstance(generated, str) and len(generated) >= 8

    # Alice can sign in with the generated password.
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "alice@acme.example.com", "password": generated},
        headers={"X-Product-Slug": "invite-co"},
    )
    assert r.status_code == 200, r.text

    # Admin-supplied password is echoed back unchanged.
    r = await client.post(
        "/api/v1/users",
        json={
            "email": "bob@acme.example.com",
            "role_codes": ["member"],
            "initial_password": "ChooseMe123!",
        },
        headers={**platform_admin_headers(), "X-Product-Slug": "invite-co"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["initial_password"] == "ChooseMe123!"


@pytest.mark.asyncio
async def test_reinvited_user_can_log_in_with_new_password(client: AsyncClient) -> None:
    """After invite → delete → re-invite, the new password works. Used to
    fail: login query returned the (soft-deleted, is_active=False) old
    row in undefined order, raising 'invalid credentials'."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Login Recycle", "slug": "login-recycle"},
        headers=platform_admin_headers(),
    )
    await client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
        headers={**platform_admin_headers(), "X-Product-Slug": "login-recycle"},
    )

    # Round 1
    r1 = await client.post(
        "/api/v1/users",
        json={"email": "user@acme.example.com", "role_codes": ["member"],
              "initial_password": "Round1Password!"},
        headers={**platform_admin_headers(), "X-Product-Slug": "login-recycle"},
    )
    assert r1.status_code == 201
    user_id_1 = r1.json()["id"]

    # Delete
    r = await client.delete(
        f"/api/v1/users/{user_id_1}",
        headers={**platform_admin_headers(), "X-Product-Slug": "login-recycle"},
    )
    assert r.status_code == 204

    # Round 2 — same email, fresh password
    r2 = await client.post(
        "/api/v1/users",
        json={"email": "user@acme.example.com", "role_codes": ["member"],
              "initial_password": "Round2Password!"},
        headers={**platform_admin_headers(), "X-Product-Slug": "login-recycle"},
    )
    assert r2.status_code == 201
    assert r2.json()["id"] != user_id_1

    # The new password works.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@acme.example.com", "password": "Round2Password!"},
        headers={"X-Product-Slug": "login-recycle"},
    )
    assert ok.status_code == 200, ok.text

    # The old password does not.
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@acme.example.com", "password": "Round1Password!"},
        headers={"X-Product-Slug": "login-recycle"},
    )
    assert bad.status_code == 401, bad.text


@pytest.mark.asyncio
async def test_admin_purchase_creates_subscription_when_none_exists(
    client: AsyncClient,
) -> None:
    """Admin scopes into a tenant that has no subscription yet (e.g.
    created via /tenants without owner+plan_code) and clicks Purchase.
    Used to 404 'subscription not found' because purchase() called
    _get_or_raise first. Now it upserts."""
    # Bootstrap product with standard plans + a tenant with NO sub.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "P Test", "slug": "p-test"},
        headers=platform_admin_headers(),
    )
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},  # no owner / plan_code
        headers={**platform_admin_headers(), "X-Product-Slug": "p-test"},
    )
    assert r.status_code == 201, r.text

    # GET shows no subscription.
    r = await client.get(
        "/api/v1/subscription",
        headers={**platform_admin_headers(), "X-Product-Slug": "p-test",
                 "X-Acting-Tenant-Slug": "acme"},
    )
    assert r.status_code == 404

    # Purchase Pro → creates a fresh ACTIVE subscription.
    r = await client.post(
        "/api/v1/subscription/purchase",
        json={"plan_code": "pro"},
        headers={**platform_admin_headers(), "X-Product-Slug": "p-test",
                 "X-Acting-Tenant-Slug": "acme"},
    )
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["plan_code"] == "pro"
    assert sub["status"] == "active"
    assert sub["has_access"] is True

    # GET now returns it.
    r = await client.get(
        "/api/v1/subscription",
        headers={**platform_admin_headers(), "X-Product-Slug": "p-test",
                 "X-Acting-Tenant-Slug": "acme"},
    )
    assert r.status_code == 200
    assert r.json()["plan_code"] == "pro"


@pytest.mark.asyncio
async def test_can_reinvite_user_after_soft_delete(client: AsyncClient) -> None:
    """Soft-deleted users free up their email for re-invite. Both the
    service pre-check and the DB unique index (partial WHERE deleted_at
    IS NULL) must agree, otherwise this 409s with the generic
    IntegrityError envelope."""
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Recycle", "slug": "recycle"},
        headers=platform_admin_headers(),
    )
    await client.post(
        "/api/v1/tenants",
        json={"name": "Acme", "slug": "acme"},
        headers={**platform_admin_headers(), "X-Product-Slug": "recycle"},
    )

    # First invite.
    r = await client.post(
        "/api/v1/users",
        json={"email": "x@example.com", "role_codes": ["member"]},
        headers={**platform_admin_headers(), "X-Product-Slug": "recycle"},
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    # Soft-delete.
    r = await client.delete(
        f"/api/v1/users/{user_id}",
        headers={**platform_admin_headers(), "X-Product-Slug": "recycle"},
    )
    assert r.status_code == 204, r.text

    # Re-invite same email — should succeed with a fresh user row.
    r = await client.post(
        "/api/v1/users",
        json={"email": "x@example.com", "role_codes": ["member"]},
        headers={**platform_admin_headers(), "X-Product-Slug": "recycle"},
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert new_id != user_id


@pytest.mark.asyncio
async def test_admin_create_plan_does_not_fk_violate_on_audit(
    client: AsyncClient,
) -> None:
    """Regression: admin's synthetic user id (00000000-...) used to land in
    audit_log.actor_user_id which has an FK to users — the resulting
    IntegrityError was caught by the generic handler and returned to the
    user as 'Resource already exists or violates a constraint', which was
    confusing on a plain create. Admin should now have actor_user_id=NULL
    in audit and the create should succeed."""
    # Empty product so the plan create itself is uncontested.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "FK Test", "slug": "fk-test", "seed_plans": False},
        headers=platform_admin_headers(),
    )
    r = await client.post(
        "/api/v1/plans",
        json={
            "code": "custom", "name": "Custom",
            "price_cents": 0, "currency": "USD", "interval": "month",
            "trial_days": 0, "is_public": True, "features": [],
        },
        headers={**platform_admin_headers(), "X-Product-Slug": "fk-test"},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_admin_can_create_child_tenant_in_populated_product(
    client: AsyncClient,
) -> None:
    """When a product already has a root tenant, admin's effective tenant
    becomes that root and child creation works without parent_id."""
    # Seed a product with a root tenant via normal register flow.
    await client.post(
        "/api/v1/admin/products",
        json={"name": "Populated", "slug": "populated-prod"},
        headers=platform_admin_headers(),
    )
    # Admin creates the root directly (no need to register a user).
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Pop Root", "slug": "pop-root"},
        headers={**platform_admin_headers(), "X-Product-Slug": "populated-prod"},
    )
    assert r.status_code == 201, r.text

    # Admin creates a child of the root — parent_id resolves to root, not NIL.
    r = await client.post(
        "/api/v1/tenants",
        json={"name": "Pop Child", "slug": "pop-child"},
        headers={**platform_admin_headers(), "X-Product-Slug": "populated-prod"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "pop-child"
    assert body["is_root"] is False
    assert body["parent_id"] is not None
