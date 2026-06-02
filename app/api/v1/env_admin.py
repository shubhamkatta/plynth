"""Admin routes for the per-product env-vars vault + service tokens.

Mounted at ``/admin/products/{slug}``. Gated by ``require_platform_admin``.

Three resource groups:
- ``/env``                 — CRUD for the secrets vault
- ``/env/{KEY}?reveal=...``— audited single-value reveal
- ``/service-tokens``      — issue / list / revoke the tokens products
                             use to call ``GET /api/v1/env`` at runtime
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
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
from app.schemas.env_var import (
    EnvVarDetail,
    EnvVarListItem,
    EnvVarPatch,
    EnvVarSet,
)
from app.schemas.service_token import (
    ServiceTokenCreate,
    ServiceTokenIssued,
    ServiceTokenResponse,
)
from app.services import env_var as env_svc
from app.services import product as product_svc
from app.services import service_token as token_svc

router = APIRouter(dependencies=[Depends(require_platform_admin)])

_KEY_RE = r"^[A-Z][A-Z0-9_]{0,127}$"


async def _resolve_product_slug(db: AsyncSession, slug: str) -> UUID:
    """Resolve `{slug}` path param to a product_id and prime the audit
    context. Mirrors the helper in webhooks_admin.py."""
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


# ---------------------------------------------------------------------
# Env vars
# ---------------------------------------------------------------------

@router.get("/env", response_model=list[EnvVarListItem],
            summary="List env vars (masked previews only)")
async def list_env_vars(
    slug: Annotated[str, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[EnvVarListItem]:
    pid = await _resolve_product_slug(db, slug)
    rows = await env_svc.list_vars(db, product_id=pid)
    out: list[EnvVarListItem] = []
    for r in rows:
        item = EnvVarListItem(
            key=r.key,
            is_secret=r.is_secret,
            description=r.description,
            last_rotated_at=r.last_rotated_at,
        )
        if r.is_secret:
            item.preview = env_svc.preview(r)
        else:
            item.value = env_svc.reveal(r)
        out.append(item)
    return out


@router.put("/env/{key}", response_model=EnvVarListItem,
            summary="Create or rotate a single env var")
async def set_env_var(
    slug: Annotated[str, Path()],
    key:  Annotated[str, Path(pattern=_KEY_RE, max_length=128)],
    payload: EnvVarSet,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnvVarListItem:
    pid = await _resolve_product_slug(db, slug)
    row = await env_svc.set_var(
        db,
        product_id=pid,
        key=key,
        value=payload.value,
        is_secret=payload.is_secret,
        description=payload.description,
    )
    item = EnvVarListItem(
        key=row.key,
        is_secret=row.is_secret,
        description=row.description,
        last_rotated_at=row.last_rotated_at,
    )
    if row.is_secret:
        item.preview = env_svc.preview(row)
    else:
        item.value = env_svc.reveal(row)
    return item


@router.patch("/env/{key}", response_model=EnvVarListItem,
              summary="Patch env var metadata (use PUT to rotate the value)")
async def patch_env_var(
    slug: Annotated[str, Path()],
    key:  Annotated[str, Path(pattern=_KEY_RE, max_length=128)],
    payload: EnvVarPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnvVarListItem:
    pid = await _resolve_product_slug(db, slug)
    row = await env_svc.get_var(db, product_id=pid, key=key)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("no fields to patch")
    if "is_secret" in changes:
        # Toggling is_secret re-encodes the stored bytes accordingly so
        # the row stays self-consistent. We rotate via set_var to share
        # the audit row and last_rotated_at stamp.
        plaintext = env_svc.reveal(row)
        row = await env_svc.set_var(
            db,
            product_id=pid,
            key=key,
            value=plaintext,
            is_secret=changes["is_secret"],
            description=changes.get("description", row.description),
        )
    elif "description" in changes:
        row.description = changes["description"]
        await db.flush()
    item = EnvVarListItem(
        key=row.key, is_secret=row.is_secret,
        description=row.description, last_rotated_at=row.last_rotated_at,
    )
    if row.is_secret:
        item.preview = env_svc.preview(row)
    else:
        item.value = env_svc.reveal(row)
    return item


@router.get("/env/{key}", response_model=EnvVarDetail,
            summary="Reveal one env var (audited; requires reason)")
async def reveal_env_var(
    slug: Annotated[str, Path()],
    key:  Annotated[str, Path(pattern=_KEY_RE, max_length=128)],
    db:   Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    reveal: Annotated[bool, Query()] = False,
    reason: Annotated[str | None, Query(min_length=3, max_length=255)] = None,
) -> EnvVarDetail:
    if not reveal:
        raise ValidationFailed("pass ?reveal=true&reason=... to reveal the value")
    if not reason:
        raise ValidationFailed("reason is required when revealing")
    pid = await _resolve_product_slug(db, slug)
    row = await env_svc.get_var(db, product_id=pid, key=key)
    plaintext = env_svc.reveal(row)
    await env_svc.record_reveal(
        db,
        product_id=pid,
        key=key,
        actor_user_id=None,  # platform-admin reveal — no user JWT
        reason=reason,
        ip_address=request.client.host if request.client else None,
    )
    return EnvVarDetail(
        key=row.key,
        value=plaintext,
        is_secret=row.is_secret,
        description=row.description,
        last_rotated_at=row.last_rotated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/env/{key}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete an env var")
async def delete_env_var(
    slug: Annotated[str, Path()],
    key:  Annotated[str, Path(pattern=_KEY_RE, max_length=128)],
    db:   Annotated[AsyncSession, Depends(get_db)],
) -> None:
    pid = await _resolve_product_slug(db, slug)
    await env_svc.delete_var(db, product_id=pid, key=key)


# ---------------------------------------------------------------------
# Service tokens
# ---------------------------------------------------------------------

@router.post("/service-tokens", response_model=ServiceTokenIssued,
             status_code=status.HTTP_201_CREATED,
             summary="Issue a service token (secret returned once)")
async def issue_service_token(
    slug: Annotated[str, Path()],
    payload: ServiceTokenCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceTokenIssued:
    pid = await _resolve_product_slug(db, slug)
    row, raw = await token_svc.issue(
        db,
        product_id=pid,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    return ServiceTokenIssued(
        id=row.id, name=row.name, scopes=row.scopes,
        expires_at=row.expires_at, revoked_at=row.revoked_at,
        last_used_at=row.last_used_at, last_used_ip=row.last_used_ip,
        created_at=row.created_at, updated_at=row.updated_at,
        token=raw,
    )


@router.get("/service-tokens", response_model=list[ServiceTokenResponse])
async def list_service_tokens(
    slug: Annotated[str, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ServiceTokenResponse]:
    pid = await _resolve_product_slug(db, slug)
    rows = await token_svc.list_for_product(db, product_id=pid)
    return [
        ServiceTokenResponse(
            id=r.id, name=r.name, scopes=r.scopes,
            expires_at=r.expires_at, revoked_at=r.revoked_at,
            last_used_at=r.last_used_at, last_used_ip=r.last_used_ip,
            created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.delete("/service-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke a service token (irreversible)")
async def revoke_service_token(
    slug: Annotated[str, Path()],
    token_id: Annotated[UUID, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    pid = await _resolve_product_slug(db, slug)
    await token_svc.revoke(db, product_id=pid, token_id=token_id)
