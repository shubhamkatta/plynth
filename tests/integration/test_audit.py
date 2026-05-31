"""Audit log writes for key state changes."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.audit import AuditLog
from tests.conftest import auth, product_headers, register_tenant


async def _actions_for_tenant(tenant_id: str) -> list[str]:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            rows = (await db.scalars(
                select(AuditLog.action).where(AuditLog.tenant_id == tenant_id)
                .order_by(AuditLog.created_at)
            )).all()
    return list(rows)


@pytest.mark.asyncio
async def test_register_emits_audit_chain(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    tid = me.json()["tenant_id"]
    actions = await _actions_for_tenant(tid)
    assert "tenant.create" in actions
    assert "user.register" in actions
    # Default seeded plan is Free ($0) — start_trial activates it immediately
    # (no trial period). Paid-plan signups would emit subscription.trial_started.
    assert "subscription.activated_free" in actions


@pytest.mark.asyncio
async def test_failed_login_recorded(client: AsyncClient) -> None:
    await register_tenant(client, slug="acme")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@acme.example.com", "password": "WrongPassword99!",
              "tenant_slug": "acme"},
        headers=product_headers("producta"),
    )
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            row = await db.scalar(
                select(AuditLog).where(AuditLog.action == "user.login_failed")
            )
    assert row is not None
    assert row.diff.get("reason") == "bad_password"


@pytest.mark.asyncio
async def test_subscription_change_emits_upgrade_action(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    tid = me.json()["tenant_id"]
    await client.post(
        "/api/v1/subscription/purchase", json={"plan_code": "free"},
        headers=auth(tok["access_token"]),
    )
    await client.post(
        "/api/v1/subscription/change", json={"plan_code": "pro"},
        headers=auth(tok["access_token"]),
    )
    actions = await _actions_for_tenant(tid)
    assert "subscription.purchase" in actions
    assert "subscription.upgrade" in actions


@pytest.mark.asyncio
async def test_user_lifecycle_audit_trail(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    me = await client.get("/api/v1/auth/me", headers=auth(tok["access_token"]))
    tid = me.json()["tenant_id"]
    invited = await client.post(
        "/api/v1/users",
        json={"email": "track@acme.example.com", "role_codes": ["member"]},
        headers=auth(tok["access_token"]),
    )
    uid = invited.json()["id"]
    await client.post(f"/api/v1/users/{uid}/deactivate", headers=auth(tok["access_token"]))
    await client.post(f"/api/v1/users/{uid}/activate", headers=auth(tok["access_token"]))
    await client.delete(f"/api/v1/users/{uid}", headers=auth(tok["access_token"]))
    actions = await _actions_for_tenant(tid)
    for expected in ("user.invite", "user.deactivate", "user.activate", "user.delete"):
        assert expected in actions, f"missing {expected} in {actions}"
