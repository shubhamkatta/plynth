"""User-facing routes for components.

Two surfaces:
- ``GET /api/v1/components`` — list active components in the current
  product. Public to any authenticated user; the response includes
  whether the *current* user has access to each.
- ``GET / PUT / DELETE /api/v1/users/{user_id}/components/...`` —
  tenant-admin override management. Gated by ``components:override``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.component import ProductComponent
from app.models.user import User
from app.schemas.component import (
    UserComponentOverrideSet,
    UserComponentStatus,
)
from app.services import component as component_svc

router = APIRouter()
users_router = APIRouter()

_CODE_RE = r"^[a-z][a-z0-9_-]{0,63}$"


def _to_status(
    c: ProductComponent, is_enabled: bool, source: str, reason: str | None,
) -> UserComponentStatus:
    """Shape a (component, decision) tuple into the response schema,
    including ``required_plan_codes`` when the gate is the reason for
    the answer so clients can render upgrade prompts."""
    return UserComponentStatus(
        code=c.code, name=c.name, is_enabled=is_enabled,
        source=source, description=c.description, reason=reason,
        required_plan_codes=(c.required_plan_codes if source == "plan" else None),
    )


@router.get("", response_model=list[UserComponentStatus],
            summary="List active components in the current product with my access")
async def list_my_components(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserComponentStatus]:
    rows = await component_svc.user_effective_components(db, user=user)
    return [_to_status(c, e, s, r) for (c, e, s, r) in rows]


# --- user override management (tenant admin) -------------------------

async def _load_user_in_tenant(
    db: AsyncSession, *, user_id: UUID, product_id: UUID, tenant_id: UUID
) -> User:
    """The target user must be in the SAME tenant as the calling admin.
    No cross-tenant overrides allowed — that's an admin-of-admin call."""
    with bypass_product(), bypass_tenant():
        target = await db.get(User, user_id)
    if (
        target is None
        or target.deleted_at is not None
        or target.product_id != product_id
        or target.tenant_id != tenant_id
    ):
        raise NotFound(f"user {user_id} not in current tenant")
    return target


@users_router.get("/{user_id}/components", response_model=list[UserComponentStatus],
                  dependencies=[Depends(require_permission("components:read"))])
async def list_user_components(
    user_id: Annotated[UUID, Path()],
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserComponentStatus]:
    target = await _load_user_in_tenant(
        db, user_id=user_id, product_id=actor.product_id, tenant_id=actor.tenant_id,
    )
    rows = await component_svc.user_effective_components(db, user=target)
    return [_to_status(c, e, s, r) for (c, e, s, r) in rows]


@users_router.put(
    "/{user_id}/components/{code}",
    response_model=UserComponentStatus,
    dependencies=[Depends(require_permission("components:override"))],
    summary="Set a per-user override (enable or disable a component for one user)",
)
async def set_user_component_override(
    user_id: Annotated[UUID, Path()],
    code: Annotated[str, Path(pattern=_CODE_RE, max_length=64)],
    payload: UserComponentOverrideSet,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserComponentStatus:
    target = await _load_user_in_tenant(
        db, user_id=user_id, product_id=actor.product_id, tenant_id=actor.tenant_id,
    )
    await component_svc.set_user_override(
        db,
        product_id=actor.product_id,
        user_id=target.id,
        tenant_id=target.tenant_id,
        code=code,
        is_enabled=payload.is_enabled,
        reason=payload.reason,
        actor_user_id=actor.id,
    )
    component = await component_svc.get_component(db, product_id=actor.product_id, code=code)
    return UserComponentStatus(
        code=component.code, name=component.name,
        is_enabled=payload.is_enabled, source="override",
        description=component.description, reason=payload.reason,
    )


@users_router.delete(
    "/{user_id}/components/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("components:override"))],
    summary="Clear a per-user override (revert to component default)",
)
async def clear_user_component_override(
    user_id: Annotated[UUID, Path()],
    code: Annotated[str, Path(pattern=_CODE_RE, max_length=64)],
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    target = await _load_user_in_tenant(
        db, user_id=user_id, product_id=actor.product_id, tenant_id=actor.tenant_id,
    )
    await component_svc.clear_user_override(
        db,
        product_id=actor.product_id,
        user_id=target.id,
        code=code,
        actor_user_id=actor.id,
    )
