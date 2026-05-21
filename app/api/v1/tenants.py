from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import Forbidden, NotFound
from app.core.tenant import current_tenant_id
from app.models.tenant import Tenant, TenantStatus
from app.schemas.tenant import (
    AccessibleChildResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)
from app.services import tenant as tenant_svc

router = APIRouter()


@router.get("", response_model=list[TenantResponse],
            dependencies=[Depends(require_permission("tenants:read"))])
async def list_tenants(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[Tenant]:
    """Return the effective tenant + its children. Scope honors act-as."""
    tid = current_tenant_id() or user.tenant_id
    return list((await db.scalars(
        select(Tenant).where(
            Tenant.product_id == user.product_id,
            (Tenant.id == tid) | (Tenant.parent_id == tid),
        )
    )).all())


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("tenants:write"))])
async def create_child_tenant(
    payload: TenantCreate, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> Tenant:
    from uuid import UUID
    NIL_TENANT = UUID("00000000-0000-0000-0000-000000000000")
    is_admin = getattr(user, "is_platform_admin", False)

    tid = current_tenant_id() or user.tenant_id

    # Platform-admin bootstrap path: in an empty product (no root tenant
    # yet), admin's effective tenant is the NIL sentinel. Treat this call
    # as "create the first root tenant" and pass parent_id=None.
    if is_admin and tid == NIL_TENANT and payload.parent_id is None:
        parent_id = None
        actor_user_id = None  # synthetic admin user — no real actor row.
    else:
        parent_id = payload.parent_id or tid
        if parent_id != tid:
            raise Forbidden("can only create child tenants under your own (effective) tenant")
        actor_user_id = None if is_admin else user.id

    return await tenant_svc.create_tenant(
        db,
        product_id=user.product_id,
        name=payload.name,
        slug=payload.slug,
        parent_id=parent_id,
        settings=payload.settings,
        actor_user_id=actor_user_id,
    )


@router.patch("/{tenant_id}", response_model=TenantResponse,
              dependencies=[Depends(require_permission("tenants:write"))])
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.product_id != user.product_id:
        raise NotFound("tenant not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, k, v)
    await db.flush()
    return tenant


@router.get("/children", response_model=list[AccessibleChildResponse],
            dependencies=[Depends(require_permission("tenants:read"))])
async def list_children(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[AccessibleChildResponse]:
    """List direct children of the caller's *home* tenant, with a per-child
    `can_act_as` flag. UIs use this to render a "switch tenant" picker.

    Always evaluated against the home tenant — switching context with
    `X-Acting-Tenant-Slug` doesn't change which children you can switch into."""
    rows = await tenant_svc.list_accessible_children(db, user=user)
    return [
        AccessibleChildResponse(
            id=r.id, slug=r.slug, name=r.name, status=r.status,
            can_act_as=r.can_act_as, reason=r.reason,
        )
        for r in rows
    ]


@router.post("/{tenant_id}/deactivate", response_model=TenantResponse,
             dependencies=[Depends(require_permission("tenants:write"))])
async def deactivate(
    tenant_id: UUID, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.product_id != user.product_id:
        raise NotFound("tenant not found")
    return await tenant_svc.set_status(
        db, tenant_id=tenant_id, status=TenantStatus.DEACTIVATED, actor_user_id=user.id
    )


@router.post("/{tenant_id}/activate", response_model=TenantResponse,
             dependencies=[Depends(require_permission("tenants:write"))])
async def activate(
    tenant_id: UUID, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.product_id != user.product_id:
        raise NotFound("tenant not found")
    return await tenant_svc.set_status(
        db, tenant_id=tenant_id, status=TenantStatus.ACTIVE, actor_user_id=user.id
    )
