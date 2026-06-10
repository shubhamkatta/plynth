"""Admin routes for the per-product component catalog.

Mounted at ``/admin/products/{slug}/components``. Gated by
``require_platform_admin``.

Component catalog is owned by the platform. Per-user overrides (the
common operator task) live under ``/users/{user_id}/components`` in
``app/api/v1/components.py`` and are gated by RBAC.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_platform_admin
from app.core.exceptions import NotFound, ValidationFailed
from app.core.tenant import (
    bypass_product,
    bypass_tenant,
    set_current_product,
    set_current_tenant,
)
from app.models.tenant import Tenant
from app.schemas.component import (
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
)
from app.services import component as component_svc
from app.services import product as product_svc

router = APIRouter(dependencies=[Depends(require_platform_admin)])

_CODE_RE = r"^[a-z][a-z0-9-]{0,63}$"


async def _resolve_product_slug(db: AsyncSession, slug: str) -> UUID:
    """Resolve `{slug}` path param to a product_id and prime audit
    context. Mirrors the helper in env_admin.py and webhooks_admin.py."""
    with bypass_product(), bypass_tenant():
        product = await product_svc.get_by_slug(db, slug)
    if product is None:
        raise NotFound(f"product {slug!r} not found")
    set_current_product(product.id)
    with bypass_product(), bypass_tenant():
        root = await db.scalar(
            select(Tenant)
            .where(
                Tenant.product_id == product.id,
                Tenant.parent_id.is_(None),
                Tenant.deleted_at.is_(None),
            )
            .order_by(Tenant.created_at)
            .limit(1)
        )
    if root is not None:
        set_current_tenant(root.id)
    return product.id


@router.get("", response_model=list[ComponentResponse],
            summary="List components (admin view — includes inactive)")
async def list_components_admin(
    slug: Annotated[str, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ComponentResponse]:
    pid = await _resolve_product_slug(db, slug)
    rows = await component_svc.list_components(db, product_id=pid, include_inactive=True)
    return [ComponentResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post("", response_model=ComponentResponse, status_code=status.HTTP_201_CREATED,
             summary="Create a component")
async def create_component_admin(
    slug: Annotated[str, Path()],
    payload: ComponentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComponentResponse:
    pid = await _resolve_product_slug(db, slug)
    row = await component_svc.create_component(
        db,
        product_id=pid,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        is_default_enabled=payload.is_default_enabled,
        is_active=payload.is_active,
        settings=payload.settings,
    )
    return ComponentResponse.model_validate(row, from_attributes=True)


@router.patch("/{code}", response_model=ComponentResponse,
              summary="Update a component (name / description / default / active / settings)")
async def update_component_admin(
    slug: Annotated[str, Path()],
    code: Annotated[str, Path(pattern=_CODE_RE, max_length=64)],
    payload: ComponentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComponentResponse:
    pid = await _resolve_product_slug(db, slug)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("no fields to patch")
    row = await component_svc.update_component(db, product_id=pid, code=code, changes=changes)
    return ComponentResponse.model_validate(row, from_attributes=True)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a component (cascades to user overrides)")
async def delete_component_admin(
    slug: Annotated[str, Path()],
    code: Annotated[str, Path(pattern=_CODE_RE, max_length=64)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    pid = await _resolve_product_slug(db, slug)
    await component_svc.delete_component(db, product_id=pid, code=code)
