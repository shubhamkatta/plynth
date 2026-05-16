from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import Forbidden, NotFound
from app.core.tenant import current_tenant_id
from app.models.permission import Permission, RolePermission
from app.models.role import Role
from app.models.user import User
from app.schemas.role import AssignRoleRequest, RoleCreate, RoleResponse, RoleUpdate
from app.services import audit, rbac

router = APIRouter()


def _serialise(role: Role) -> RoleResponse:
    perms = [rp.permission.code for rp in role.permissions]
    return RoleResponse(
        id=role.id, created_at=role.created_at, updated_at=role.updated_at,
        tenant_id=role.tenant_id, name=role.name, description=role.description,
        is_system=role.is_system, permissions=perms,
    )


@router.get("", response_model=list[RoleResponse],
            dependencies=[Depends(require_permission("roles:read"))])
async def list_roles(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[RoleResponse]:
    tid = current_tenant_id() or user.tenant_id
    stmt = (
        select(Role)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .where(
            Role.product_id == user.product_id,
            (Role.tenant_id == tid) | (Role.tenant_id.is_(None)),
        )
    )
    return [_serialise(r) for r in (await db.scalars(stmt)).all()]


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("roles:write"))])
async def create_role(
    payload: RoleCreate, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> RoleResponse:
    async with audit.audit_action(
        db, action="role.create", actor_user_id=user.id,
        resource_type="role", diff={"name": payload.name},
    ) as extras:
        tid = current_tenant_id() or user.tenant_id
        role = Role(
            product_id=user.product_id, tenant_id=tid,
            name=payload.name, description=payload.description,
        )
        db.add(role)
        await db.flush()

        for code in payload.permission_codes:
            perm = await db.scalar(select(Permission).where(Permission.code == code))
            if perm is None:
                raise NotFound(f"permission {code!r} not found")
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await db.flush()
        extras["role_id"] = str(role.id)
        extras["permission_codes"] = payload.permission_codes
    fresh = await db.scalar(
        select(Role)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .where(Role.id == role.id)
        .execution_options(populate_existing=True)
    )
    return _serialise(fresh)  # type: ignore[arg-type]


@router.patch("/{role_id}", response_model=RoleResponse,
              dependencies=[Depends(require_permission("roles:write"))])
async def update_role(
    role_id: UUID,
    payload: RoleUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoleResponse:
    role = await db.scalar(
        select(Role)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .where(Role.id == role_id, Role.product_id == user.product_id)
    )
    if role is None:
        raise NotFound("role not found")
    if role.is_system:
        raise Forbidden("system roles are immutable")

    changes = payload.model_dump(exclude_unset=True)
    async with audit.audit_action(
        db, action="role.update", actor_user_id=user.id,
        resource_type="role", resource_id=role.id, diff={"changes": changes},
    ):
        if payload.name is not None:
            role.name = payload.name
        if payload.description is not None:
            role.description = payload.description
        if payload.permission_codes is not None:
            for rp in list(role.permissions):
                await db.delete(rp)
            for code in payload.permission_codes:
                perm = await db.scalar(select(Permission).where(Permission.code == code))
                if perm is None:
                    raise NotFound(f"permission {code!r} not found")
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await db.flush()
    fresh = await db.scalar(
        select(Role)
        .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
        .where(Role.id == role.id)
        .execution_options(populate_existing=True)
    )
    return _serialise(fresh)  # type: ignore[arg-type]


@router.post("/assign", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[Depends(require_permission("roles:write"))])
async def assign(
    payload: AssignRoleRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    # Both user + role must be in the actor's product.
    target_user = await db.get(User, payload.user_id)
    if target_user is None or target_user.product_id != user.product_id:
        raise NotFound("user not found in this product")
    target_role = await db.get(Role, payload.role_id)
    if target_role is None or target_role.product_id != user.product_id:
        raise NotFound("role not found in this product")

    async with audit.audit_action(
        db, action="role.assign", actor_user_id=user.id,
        resource_type="user", resource_id=payload.user_id,
        diff={"role_id": str(payload.role_id),
              "scope_tenant_id": str(payload.scope_tenant_id) if payload.scope_tenant_id else None},
    ):
        await rbac.assign_role(
            db, user_id=payload.user_id, role_id=payload.role_id,
            product_id=user.product_id, scope_tenant_id=payload.scope_tenant_id,
        )


@router.get("/permissions", response_model=list[str],
            dependencies=[Depends(require_permission("roles:read"))])
async def list_permissions(db: Annotated[AsyncSession, Depends(get_db)]) -> list[str]:
    return sorted((await db.scalars(select(Permission.code))).all())
