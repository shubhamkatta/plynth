"""FastAPI dependencies: product resolution, current user, current tenant,
permission checks, platform-admin token.
"""

from typing import Annotated
from uuid import UUID

import jwt
import structlog
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.security import decode_token
from app.core.tenant import (
    bypass_product,
    bypass_tenant,
    set_acting_from_tenant,
    set_current_product,
    set_current_tenant,
)
from app.models.product import Product, ProductStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import product as product_svc

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login", auto_error=False)


# --- product context ------------------------------------------------------------

async def resolve_product(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_product_slug: Annotated[str | None, Header(alias="X-Product-Slug")] = None,
) -> UUID | None:
    """Look up the product by header slug; cache via Redis. Set the
    ContextVar so repositories pick it up. Returns the product id, or None
    if no header was sent (caller decides if that's allowed)."""
    if not x_product_slug:
        return None
    with bypass_product(), bypass_tenant():
        resolved = await product_svc.resolve_slug_to_id(db, x_product_slug)
    if resolved is None:
        raise ValidationFailed(f"unknown product slug {x_product_slug!r}")
    pid, pstatus = resolved
    if pstatus != ProductStatus.ACTIVE:
        raise Forbidden(f"product {x_product_slug!r} is {pstatus.value}")
    set_current_product(pid)
    structlog.contextvars.bind_contextvars(product_id=str(pid), product_slug=x_product_slug)
    return pid


async def require_product(
    pid: Annotated[UUID | None, Depends(resolve_product)],
) -> UUID:
    if pid is None:
        raise ValidationFailed("missing X-Product-Slug header")
    return pid


RequireProduct = Annotated[UUID, Depends(require_product)]
ResolvedProduct = Annotated[UUID | None, Depends(resolve_product)]


# --- act-as (parent → child tenant switching) ---------------------------------

ACT_AS_PERMISSION = "tenants:act_as_child"


def _product_allows_act_as(product: Product) -> bool:
    """Product-level config gate. Default: True (feature on by default)."""
    features = (product.settings or {}).get("features", {})
    return bool(features.get("allow_parent_child_access", True))


def _tenant_allows_child_access(tenant: Tenant) -> bool:
    """Parent-tenant-level gate. Default: True. A parent can opt out
    (e.g. compliance) without changing the product-level setting."""
    return bool((tenant.settings or {}).get("allow_child_access", True))


async def _resolve_act_as(
    *,
    db: AsyncSession,
    user: User,
    target_slug: str,
) -> Tenant:
    """Validate that `user` may act as the tenant with `target_slug`.

    Approval requires all of:
    1. Target is a direct child of the user's home tenant (same product).
    2. Product config `features.allow_parent_child_access` is True (default).
    3. Parent tenant config `allow_child_access` is True (default).
    4. EITHER the user has `tenants:act_as_child` in their home context,
       OR they have any UserRole binding with `scope_tenant_id == target.id`
       (i.e. an explicit role inside that child).
    """
    from app.models.role import UserRole
    from app.services.rbac import user_has_permission  # local: avoid circular

    with bypass_product(), bypass_tenant():
        target = await db.scalar(
            select(Tenant).where(
                Tenant.product_id == user.product_id,
                Tenant.slug == target_slug,
                Tenant.deleted_at.is_(None),
            )
        )
    if target is None:
        raise NotFound(f"tenant {target_slug!r} not found in this product")

    if target.id == user.tenant_id:
        # No-op switch — just return the home tenant. Clients sometimes
        # send the header redundantly; don't punish them.
        return target

    if target.parent_id != user.tenant_id:
        raise Forbidden("can only act as a direct child of your home tenant")

    # Product-level gate.
    with bypass_product(), bypass_tenant():
        product = await db.get(Product, user.product_id)
    if product is None or not _product_allows_act_as(product):
        raise Forbidden("parent → child access is disabled for this product")

    # Parent-tenant-level gate.
    with bypass_product(), bypass_tenant():
        home_tenant = await db.get(Tenant, user.tenant_id)
    if home_tenant is not None and not _tenant_allows_child_access(home_tenant):
        raise Forbidden("parent → child access is disabled for your tenant")

    # Permission gate: either global act_as_child (evaluated in HOME context
    # so wildcard-scope owner/admin bindings apply), OR an explicit binding
    # in the target child.
    has_global = await user_has_permission(
        db, user, ACT_AS_PERMISSION, tenant_id=user.tenant_id
    )
    if not has_global:
        has_target_binding = bool(
            await db.scalar(
                select(UserRole.id)
                .where(
                    UserRole.user_id == user.id,
                    UserRole.scope_tenant_id == target.id,
                )
                .limit(1)
            )
        )
        if not has_target_binding:
            raise Forbidden(
                f"need {ACT_AS_PERMISSION} permission or a role binding inside {target_slug!r}"
            )

    return target


# --- auth ----------------------------------------------------------------------

async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    header_pid: ResolvedProduct,
    x_acting_tenant_slug: Annotated[
        str | None, Header(alias="X-Acting-Tenant-Slug")
    ] = None,
) -> User:
    if not token:
        raise Unauthorized("missing bearer token")
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"invalid token: {exc}") from exc

    user_id = UUID(payload["sub"])
    token_pid_raw = payload.get("pid")
    if not token_pid_raw:
        raise Unauthorized("token missing product claim")
    token_pid = UUID(token_pid_raw)

    if header_pid is not None and header_pid != token_pid:
        raise Forbidden("product header does not match token")

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise Unauthorized("user inactive or missing")
    if user.product_id != token_pid:
        raise Forbidden("token / user product mismatch")

    set_current_product(token_pid)
    # Default: act as your own home tenant.
    effective_tenant_id = user.tenant_id

    if x_acting_tenant_slug:
        target = await _resolve_act_as(db=db, user=user, target_slug=x_acting_tenant_slug)
        if target.id != user.tenant_id:
            effective_tenant_id = target.id
            set_acting_from_tenant(user.tenant_id)
            structlog.contextvars.bind_contextvars(
                acting_from_tenant_id=str(user.tenant_id),
                acting_as_tenant_slug=x_acting_tenant_slug,
            )

    set_current_tenant(effective_tenant_id)
    structlog.contextvars.bind_contextvars(
        user_id=str(user.id),
        tenant_id=str(effective_tenant_id),
        product_id=str(user.product_id),
    )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_tenant_id(user: CurrentUser) -> UUID:
    # Returns the EFFECTIVE tenant id (the child when acting-as, else home).
    from app.core.tenant import current_tenant_id
    tid = current_tenant_id()
    return tid if tid is not None else user.tenant_id


CurrentTenantId = Annotated[UUID, Depends(get_current_tenant_id)]


# --- permission -----------------------------------------------------------------

def require_permission(permission: str):
    """Dependency factory: ensures current user has the given permission
    *in the current tenant scope* (which switches when acting-as)."""
    async def _checker(
        user: CurrentUser,
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> User:
        from app.services.rbac import user_has_permission

        if not await user_has_permission(db, user, permission):
            raise Forbidden(f"missing permission: {permission}")
        return user

    return _checker


async def get_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    if idempotency_key and len(idempotency_key) > 128:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key too long")
    return idempotency_key


# --- platform admin -------------------------------------------------------------

async def require_platform_admin(
    x_platform_admin_token: Annotated[str | None, Header(alias="X-Platform-Admin-Token")] = None,
) -> None:
    if not settings.platform_admin_token:
        raise Forbidden("platform admin is not configured (PLATFORM_ADMIN_TOKEN unset)")
    if not x_platform_admin_token or x_platform_admin_token != settings.platform_admin_token:
        raise Unauthorized("invalid X-Platform-Admin-Token")
