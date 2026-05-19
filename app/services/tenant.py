"""Tenant lifecycle: create root / child, activate / deactivate.

Tenants always belong to a product. The caller must pass `product_id` —
the slug uniqueness is `(product_id, slug)` so same slug can repeat across
products.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.tenant import bypass_product, bypass_tenant
from app.models.product import Product
from app.models.tenant import Tenant, TenantStatus, TenantType
from app.models.user import User
from app.services import audit


async def create_tenant(
    db: AsyncSession,
    *,
    product_id: UUID,
    name: str,
    slug: str,
    parent_id: UUID | None = None,
    settings: dict | None = None,
    actor_user_id: UUID | None = None,
    type: TenantType = TenantType.COMPANY,
) -> Tenant:
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(Tenant).where(Tenant.product_id == product_id, Tenant.slug == slug)
        )
        if existing:
            raise Conflict(f"slug {slug!r} already taken in this product")

        if parent_id:
            parent = await db.get(Tenant, parent_id)
            if parent is None or parent.product_id != product_id:
                raise NotFound(f"parent tenant {parent_id} not found in product")
            if not parent.is_root:
                raise ValidationFailed("only root tenants can have children (single-level hierarchy)")

        tenant = Tenant(
            product_id=product_id,
            name=name,
            slug=slug,
            parent_id=parent_id,
            is_root=parent_id is None,
            settings=settings or {},
            status=TenantStatus.ACTIVE,
            type=type,
        )
        db.add(tenant)
        await db.flush()
        await audit.record(
            db,
            action="tenant.create",
            actor_user_id=actor_user_id,
            resource_type="tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            product_id=product_id,
            diff={"name": name, "slug": slug, "type": type.value,
                  "parent_id": str(parent_id) if parent_id else None},
        )
    return tenant


@dataclass(slots=True)
class AccessibleChild:
    id: UUID
    slug: str
    name: str
    status: TenantStatus
    can_act_as: bool
    reason: str | None  # populated when can_act_as is False


async def list_accessible_children(
    db: AsyncSession, *, user: User
) -> list[AccessibleChild]:
    """List the children of the user's home tenant, annotated with whether
    the user can `act_as` each child. Mirrors `_resolve_act_as` exactly so
    UIs don't get a false-positive picker.
    """
    from app.core.dependencies import (
        ACT_AS_PERMISSION,
        _product_allows_act_as,
        _tenant_allows_child_access,
    )
    from app.models.role import UserRole
    from app.services.rbac import user_has_permission

    with bypass_product(), bypass_tenant():
        product = await db.get(Product, user.product_id)
        home_tenant = await db.get(Tenant, user.tenant_id)
        children = (
            await db.scalars(
                select(Tenant)
                .where(
                    Tenant.product_id == user.product_id,
                    Tenant.parent_id == user.tenant_id,
                    Tenant.deleted_at.is_(None),
                )
                .order_by(Tenant.slug)
            )
        ).all()

    # Compute the global gates once.
    if product is None or not _product_allows_act_as(product):
        global_block = "product disabled parent → child access"
    elif home_tenant is not None and not _tenant_allows_child_access(home_tenant):
        global_block = "parent tenant disabled child access"
    else:
        global_block = None

    has_global_perm = (
        global_block is None
        and await user_has_permission(
            db, user, ACT_AS_PERMISSION, tenant_id=user.tenant_id
        )
    )
    target_scoped_ids: set = set()
    if global_block is None and not has_global_perm:
        # Pull every binding scoped to a specific tenant for this user.
        target_scoped_ids = set(
            (
                await db.scalars(
                    select(UserRole.scope_tenant_id).where(
                        UserRole.user_id == user.id,
                        UserRole.scope_tenant_id.is_not(None),
                    )
                )
            ).all()
        )

    out: list[AccessibleChild] = []
    for c in children:
        if global_block is not None:
            out.append(AccessibleChild(
                id=c.id, slug=c.slug, name=c.name, status=c.status,
                can_act_as=False, reason=global_block,
            ))
            continue
        if has_global_perm or c.id in target_scoped_ids:
            out.append(AccessibleChild(
                id=c.id, slug=c.slug, name=c.name, status=c.status,
                can_act_as=True, reason=None,
            ))
        else:
            out.append(AccessibleChild(
                id=c.id, slug=c.slug, name=c.name, status=c.status,
                can_act_as=False,
                reason=f"need {ACT_AS_PERMISSION} permission or a scoped binding",
            ))
    return out


async def set_status(
    db: AsyncSession, *, tenant_id: UUID, status: TenantStatus, actor_user_id: UUID | None = None
) -> Tenant:
    with bypass_product(), bypass_tenant():
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound("tenant not found")
        before = tenant.status
        tenant.status = status
        await db.flush()
        await audit.record(
            db,
            action=f"tenant.{status.value}",
            actor_user_id=actor_user_id,
            resource_type="tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            product_id=tenant.product_id,
            diff={"from": before.value, "to": status.value},
        )
    return tenant
