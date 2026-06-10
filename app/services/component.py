"""Component catalog CRUD + per-user effective-access resolution.

Single source of truth for reading/writing rows in
``product_components`` and ``user_component_overrides``.

Effective lookup:
- ``user_effective_components(user)`` — full map for /me / list endpoints.
- ``user_has_component_access(user, code)`` — single-call gate for
  product-runtime authorisation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.component import ProductComponent, UserComponentOverride
from app.models.user import User
from app.services import audit


# ---------------------------------------------------------------------
# Component catalog (admin-managed)
# ---------------------------------------------------------------------

async def create_component(
    db: AsyncSession,
    *,
    product_id: UUID,
    code: str,
    name: str,
    description: str | None = None,
    is_default_enabled: bool = True,
    is_active: bool = True,
    settings: dict[str, Any] | None = None,
    actor_user_id: UUID | None = None,
) -> ProductComponent:
    """Idempotent on (product_id, code). Raises Conflict on duplicate."""
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(ProductComponent).where(
                ProductComponent.product_id == product_id,
                ProductComponent.code == code,
            )
        )
        if existing is not None:
            raise Conflict(f"component {code!r} already exists in this product")
        row = ProductComponent(
            product_id=product_id,
            code=code,
            name=name,
            description=description,
            is_default_enabled=is_default_enabled,
            is_active=is_active,
            settings=settings or {},
        )
        db.add(row)
        await db.flush()
        await audit.record(
            db,
            action="component.created",
            actor_user_id=actor_user_id,
            resource_type="component",
            resource_id=row.id,
            product_id=product_id,
            diff={
                "code": code,
                "is_default_enabled": is_default_enabled,
                "is_active": is_active,
            },
        )
    return row


async def list_components(
    db: AsyncSession, *, product_id: UUID, include_inactive: bool = False
) -> list[ProductComponent]:
    with bypass_product(), bypass_tenant():
        q = select(ProductComponent).where(ProductComponent.product_id == product_id)
        if not include_inactive:
            q = q.where(ProductComponent.is_active.is_(True))
        rows = (await db.scalars(q.order_by(ProductComponent.code))).all()
    return list(rows)


async def get_component(
    db: AsyncSession, *, product_id: UUID, code: str
) -> ProductComponent:
    with bypass_product(), bypass_tenant():
        row = await db.scalar(
            select(ProductComponent).where(
                ProductComponent.product_id == product_id,
                ProductComponent.code == code,
            )
        )
    if row is None:
        raise NotFound(f"component {code!r} not found in product")
    return row


async def update_component(
    db: AsyncSession,
    *,
    product_id: UUID,
    code: str,
    changes: dict[str, Any],
    actor_user_id: UUID | None = None,
) -> ProductComponent:
    row = await get_component(db, product_id=product_id, code=code)
    if not changes:
        return row
    with bypass_product(), bypass_tenant():
        for k, v in changes.items():
            setattr(row, k, v)
        await db.flush()
        await audit.record(
            db,
            action="component.updated",
            actor_user_id=actor_user_id,
            resource_type="component",
            resource_id=row.id,
            product_id=product_id,
            diff={"code": code, "changes": list(changes.keys())},
        )
    return row


async def delete_component(
    db: AsyncSession, *, product_id: UUID, code: str, actor_user_id: UUID | None = None
) -> None:
    row = await get_component(db, product_id=product_id, code=code)
    with bypass_product(), bypass_tenant():
        await db.delete(row)
        await audit.record(
            db,
            action="component.deleted",
            actor_user_id=actor_user_id,
            resource_type="component",
            resource_id=row.id,
            product_id=product_id,
            diff={"code": code},
        )


# ---------------------------------------------------------------------
# Per-user overrides
# ---------------------------------------------------------------------

async def set_user_override(
    db: AsyncSession,
    *,
    product_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    code: str,
    is_enabled: bool,
    reason: str | None = None,
    actor_user_id: UUID | None = None,
) -> UserComponentOverride:
    """Idempotent on (user_id, component_id). Updates is_enabled +
    reason + set_at if a row already exists."""
    component = await get_component(db, product_id=product_id, code=code)
    now = datetime.now(UTC)
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(UserComponentOverride).where(
                UserComponentOverride.user_id == user_id,
                UserComponentOverride.component_id == component.id,
            )
        )
        if existing is None:
            row = UserComponentOverride(
                product_id=product_id,
                tenant_id=tenant_id,
                user_id=user_id,
                component_id=component.id,
                is_enabled=is_enabled,
                reason=reason,
                set_by_user_id=actor_user_id,
                set_at=now,
            )
            db.add(row)
            action = "component.override_created"
        else:
            existing.is_enabled = is_enabled
            existing.reason = reason
            existing.set_by_user_id = actor_user_id
            existing.set_at = now
            row = existing
            action = "component.override_updated"
        await db.flush()
        await audit.record(
            db,
            action=action,
            actor_user_id=actor_user_id,
            resource_type="component_override",
            resource_id=row.id,
            product_id=product_id,
            tenant_id=tenant_id,
            diff={
                "code": code,
                "user_id": str(user_id),
                "is_enabled": is_enabled,
                "reason": reason,
            },
        )
    return row


async def clear_user_override(
    db: AsyncSession,
    *,
    product_id: UUID,
    user_id: UUID,
    code: str,
    actor_user_id: UUID | None = None,
) -> None:
    """Delete the user's override row → effective access reverts to
    the component's default. No-op if no override exists."""
    component = await get_component(db, product_id=product_id, code=code)
    with bypass_product(), bypass_tenant():
        existing = await db.scalar(
            select(UserComponentOverride).where(
                UserComponentOverride.user_id == user_id,
                UserComponentOverride.component_id == component.id,
            )
        )
        if existing is None:
            return
        await db.delete(existing)
        await audit.record(
            db,
            action="component.override_cleared",
            actor_user_id=actor_user_id,
            resource_type="component_override",
            resource_id=existing.id,
            product_id=product_id,
            tenant_id=existing.tenant_id,
            diff={"code": code, "user_id": str(user_id)},
        )


# ---------------------------------------------------------------------
# Effective access
# ---------------------------------------------------------------------

async def user_effective_components(
    db: AsyncSession, *, user: User
) -> list[tuple[ProductComponent, bool, str, str | None]]:
    """Return [(component, is_enabled, source, reason), ...] for every
    ACTIVE component in the user's product. ``source`` is "default"
    or "override". Inactive components are omitted entirely (the user
    can't reach them either way)."""
    with bypass_product(), bypass_tenant():
        components = (
            await db.scalars(
                select(ProductComponent)
                .where(
                    ProductComponent.product_id == user.product_id,
                    ProductComponent.is_active.is_(True),
                )
                .order_by(ProductComponent.code)
            )
        ).all()
        if not components:
            return []
        overrides = {
            o.component_id: o
            for o in (
                await db.scalars(
                    select(UserComponentOverride).where(
                        UserComponentOverride.user_id == user.id,
                        UserComponentOverride.component_id.in_(
                            [c.id for c in components]
                        ),
                    )
                )
            ).all()
        }
    out: list[tuple[ProductComponent, bool, str, str | None]] = []
    for c in components:
        ov = overrides.get(c.id)
        if ov is not None:
            out.append((c, ov.is_enabled, "override", ov.reason))
        else:
            out.append((c, c.is_default_enabled, "default", None))
    return out


async def user_has_component_access(
    db: AsyncSession, *, user: User, code: str
) -> bool:
    """Single-call access gate. Returns False if component is inactive
    or doesn't exist (so callers don't accidentally grant access to a
    deleted module)."""
    with bypass_product(), bypass_tenant():
        component = await db.scalar(
            select(ProductComponent).where(
                ProductComponent.product_id == user.product_id,
                ProductComponent.code == code,
            )
        )
        if component is None or not component.is_active:
            return False
        ov = await db.scalar(
            select(UserComponentOverride).where(
                UserComponentOverride.user_id == user.id,
                UserComponentOverride.component_id == component.id,
            )
        )
    if ov is not None:
        return ov.is_enabled
    return component.is_default_enabled
