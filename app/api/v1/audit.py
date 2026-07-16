"""Audit read API — the tenant-scoped audit log viewer (perm `audit:read`).

Lists `AuditLog` rows for the caller's product + effective tenant, newest
first, paginated and filterable by `action` / `resource_type`. This is a
read-only surface; audit rows are written by `app.services.audit` and are never
mutated (the append-only contract). Unblocks Mayva's Settings → Activity tab.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.tenant import current_tenant_id
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogEntry
from app.schemas.common import Page

router = APIRouter()


@router.get(
    "",
    response_model=Page[AuditLogEntry],
    dependencies=[Depends(require_permission("audit:read"))],
)
async def list_audit_log(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    action: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> Page[AuditLogEntry]:
    tid = current_tenant_id() or user.tenant_id
    filters = [AuditLog.product_id == user.product_id, AuditLog.tenant_id == tid]
    if action is not None:
        filters.append(AuditLog.action == action)
    if resource_type is not None:
        filters.append(AuditLog.resource_type == resource_type)

    total = int(
        await db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    )
    rows = list(
        (
            await db.scalars(
                select(AuditLog)
                .where(*filters)
                .order_by(AuditLog.created_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()
    )
    return Page(
        items=[AuditLogEntry.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
