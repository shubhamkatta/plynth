"""Audit log writes.

Call from every state-changing service path. Two entry points:

- `record(...)` — explicit per-action call. Use when you've already
  computed the diff or there's no clean "before / after" pair.
- `audit_action(...)` — async context manager. Writes the audit row on
  clean exit; on raise it logs a `action.failed` warning with the same
  context and re-raises (no audit row — partial / rolled-back transactions
  must not look successful in the log).

`product_id` is required (falls back to `current_product_id()`). Without
a product context the call is logged but not persisted — a platform-level
event with no product to scope to.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import (
    acting_from_tenant_id,
    current_product_id,
    current_tenant_id,
)
from app.models.audit import AuditLog

log = structlog.get_logger("audit")


def _request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor_user_id: UUID | None = None,
    actor_ip: str | None = None,
    resource_type: str | None = None,
    resource_id: str | UUID | None = None,
    diff: dict[str, Any] | None = None,
    tenant_id: UUID | None = None,
    product_id: UUID | None = None,
    acting_from_tenant_id_override: UUID | None = None,
) -> None:
    """Persist one audit-log entry. No-op if no tenant/product context.

    `acting_from_tenant_id` is auto-filled from the request context (set
    when a parent-tenant user is acting as a child via
    `X-Acting-Tenant-Slug`). Pass `acting_from_tenant_id_override` only
    from background jobs / scripts that need to override.
    """
    from uuid import UUID as _UUID
    NIL = _UUID("00000000-0000-0000-0000-000000000000")

    tid = tenant_id or current_tenant_id()
    pid = product_id or current_product_id()
    # Platform-admin operations on an empty product (no root tenant) carry
    # a NIL sentinel tenant_id from get_current_user. We must not write
    # that into audit_log.tenant_id — the FK to `tenants` would fail and
    # the IntegrityError handler would surface a misleading 409 to the
    # caller. Treat NIL as "no tenant scope" and skip the audit entry.
    if tid == NIL:
        tid = None
    if tid is None or pid is None:
        log.info(
            "audit.skipped_no_scope", action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            has_tenant=tid is not None, has_product=pid is not None,
        )
        return

    acting_from = (
        acting_from_tenant_id_override
        if acting_from_tenant_id_override is not None
        else acting_from_tenant_id()
    )
    # Guardrail: don't record self-references.
    if acting_from is not None and acting_from == tid:
        acting_from = None

    entry = AuditLog(
        product_id=pid,
        tenant_id=tid,
        acting_from_tenant_id=acting_from,
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        diff=diff or {},
        request_id=_request_id(),
    )
    db.add(entry)
    await db.flush()
    log.info(
        "audit", action=action,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        product_id=str(pid), tenant_id=str(tid),
        acting_from_tenant_id=str(acting_from) if acting_from else None,
    )


@asynccontextmanager
async def audit_action(
    db: AsyncSession,
    *,
    action: str,
    actor_user_id: UUID | None = None,
    actor_ip: str | None = None,
    resource_type: str | None = None,
    resource_id: str | UUID | None = None,
    tenant_id: UUID | None = None,
    product_id: UUID | None = None,
    diff: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run a block as a single audited action. See module docstring."""
    extras: dict[str, Any] = {}
    try:
        yield extras
    except Exception as exc:
        log.warning(
            "action.failed",
            action=action,
            actor_user_id=str(actor_user_id) if actor_user_id else None,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    merged: dict[str, Any] = {**(diff or {}), **extras}
    await record(
        db,
        action=action,
        actor_user_id=actor_user_id,
        actor_ip=actor_ip,
        resource_type=resource_type,
        resource_id=resource_id,
        diff=merged,
        tenant_id=tenant_id,
        product_id=product_id,
    )
