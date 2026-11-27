"""A prospect invite must leave an audit trail (queue T-038).

Minting a platform-admin prospect invite logged
``audit.skipped_no_scope action=invite.create has_tenant=false`` and wrote no
row at all: ``services/audit.record`` skipped the entry whenever there was no
tenant, and a prospect invite deliberately has none — the invitee gets their
own tenant when they accept. So **the single action that onboards a new
therapist or clinic was unaudited, in the system that owns identity**, with no
trail for who invited whom, when, or on what plan.

The fix narrows the skip to the one case that genuinely cannot be scoped (no
*product*) and makes ``audit_log.tenant_id`` nullable, where a null means
"product-scoped, no tenant" rather than "unknown".

These pin both halves: the row now exists, and a tenant's own audit listing
still cannot see rows that do not belong to it.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.audit import AuditLog
from tests.conftest import auth, product_id, register_tenant

PW = "a-long-enough-password-1"
ADMIN = {"X-Platform-Admin-Token": "test-platform-admin-token"}


async def _admin_invite(client: AsyncClient, slug: str, email: str, **extra) -> dict:
    r = await client.post(
        f"/api/v1/admin/products/{slug}/invites",
        json={"email": email, **extra}, headers=ADMIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _audit_rows(action: str) -> list[AuditLog]:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            return list(
                (
                    await db.scalars(
                        select(AuditLog).where(AuditLog.action == action)
                    )
                ).all()
            )


@pytest.mark.asyncio
async def test_a_prospect_invite_writes_an_audit_row(client: AsyncClient) -> None:
    await _admin_invite(
        client, "producta", "prospect@example.com",
        full_name="Pat Prospect", plan_code="practice",
    )

    rows = await _audit_rows("invite.create")
    assert len(rows) == 1, "a prospect invite must be audited — it onboards a customer"
    row = rows[0]
    # Product-scoped, no tenant: the invitee has no tenant until they accept.
    assert row.tenant_id is None
    assert row.product_id == product_id("producta")
    assert row.resource_type == "invite"
    # The trail has to answer who was invited, on what plan, by what route.
    assert row.diff["email"] == "prospect@example.com"
    assert row.diff["kind"] == "new_tenant"
    assert row.diff["plan_code"] == "practice"


@pytest.mark.asyncio
async def test_a_tenant_scoped_invite_still_carries_its_tenant(
    client: AsyncClient,
) -> None:
    """The nullable column must not quietly drop the tenant where there IS one.
    A colleague invited into an existing practice stays attributable to it."""
    tok = await register_tenant(client, slug="auditinv", email="owner@auditinv.example.com")
    r = await client.post(
        "/api/v1/users/invites",
        json={"email": "colleague@auditinv.example.com", "role_codes": ["member"]},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 201, r.text

    rows = await _audit_rows("invite.create")
    assert len(rows) == 1
    assert rows[0].tenant_id is not None
    assert rows[0].diff["kind"] == "join_tenant"


@pytest.mark.asyncio
async def test_a_tenant_cannot_see_product_scoped_rows_in_its_own_log(
    client: AsyncClient,
) -> None:
    """A null-tenant row is platform-level. It must not leak into a tenant's
    audit listing — which filters on an equality, so it cannot."""
    await _admin_invite(client, "producta", "elsewhere@example.com")
    tok = await register_tenant(client, slug="auditsee", email="owner@auditsee.example.com")

    r = await client.get(
        "/api/v1/audit?action=invite.create", headers=auth(tok["access_token"])
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
