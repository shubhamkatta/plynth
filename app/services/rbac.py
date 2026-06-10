"""Permission checks + per-product system role provisioning."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.tenant import bypass_product, bypass_tenant, current_tenant_id
from app.models.permission import Permission, RolePermission
from app.models.role import Role, UserRole
from app.models.user import User

# Default catalog. Extend per product under `app/products/<x>/permissions.py`.
SYSTEM_PERMISSIONS: list[tuple[str, str]] = [
    ("*:*", "Super admin: all actions"),
    ("tenants:read", "Read tenants"),
    ("tenants:write", "Create / update tenants"),
    ("tenants:delete", "Delete tenants"),
    ("tenants:act_as_child", "Switch context into a child tenant (parent → child)"),
    ("users:read", "Read users"),
    ("users:write", "Create / update users"),
    ("users:delete", "Delete users"),
    ("users:activate", "Activate / deactivate users"),
    ("roles:read", "Read roles"),
    ("roles:write", "Manage roles + assignments"),
    ("plans:read", "Read plans"),
    ("plans:write", "Manage plans (platform-admin)"),
    ("subscriptions:read", "Read subscription"),
    ("subscriptions:purchase", "Purchase a plan"),
    ("subscriptions:change", "Upgrade / downgrade plan"),
    ("subscriptions:cancel", "Cancel subscription"),
    ("credits:read", "Read credit balance + ledger"),
    ("credits:consume", "Consume credits"),
    ("credits:grant", "Grant credits (admin)"),
    ("audit:read", "Read audit log"),
    # Jobs API (docs/architecture.md § 6.2)
    ("jobs:read", "List + read background jobs"),
    ("jobs:write", "Enqueue a background job"),
    ("jobs:cancel", "Cancel a queued job"),
    # Storage API (docs/architecture.md § 6.3)
    ("storage:read", "Read storage collections and documents"),
    ("storage:write", "Create collections + upsert documents"),
    ("storage:delete", "Delete storage documents"),
    # Components (docs/architecture.md § 6.5)
    ("components:read", "List components + per-user effective access"),
    ("components:override", "Enable / disable a component for a specific user"),
]

SYSTEM_ROLES: dict[str, list[str]] = {
    "owner": ["*:*"],
    "admin": [
        "tenants:read", "tenants:write", "tenants:act_as_child",
        "users:read", "users:write", "users:activate",
        "roles:read", "roles:write",
        "subscriptions:read", "subscriptions:purchase",
        "subscriptions:change", "subscriptions:cancel",
        "credits:read", "credits:grant",
        "audit:read",
        # Jobs + Storage: admin gets the full surface.
        "jobs:read", "jobs:write", "jobs:cancel",
        "storage:read", "storage:write", "storage:delete",
        # Components: admins manage who in their tenant gets what.
        "components:read", "components:override",
    ],
    "member": [
        "tenants:read",
        "users:read",
        "subscriptions:read",
        "credits:read", "credits:consume",
        # Members read jobs / storage but cannot enqueue or delete by default.
        "jobs:read",
        "storage:read",
        # Members see component listings + their own access status.
        "components:read",
    ],
}


def _matches(granted: str, required: str) -> bool:
    """`*` matches any single segment; full wildcard `*:*` matches everything."""
    g_res, g_act = granted.split(":", 1)
    r_res, r_act = required.split(":", 1)
    return (g_res in ("*", r_res)) and (g_act in ("*", r_act))


async def ensure_permission_catalog(db: AsyncSession) -> dict[str, Permission]:
    """Permissions are GLOBAL across products. Idempotent."""
    existing: dict[str, Permission] = {
        p.code: p for p in (await db.scalars(select(Permission))).all()
    }
    for code, desc in SYSTEM_PERMISSIONS:
        if code not in existing:
            p = Permission(code=code, description=desc)
            db.add(p)
            existing[code] = p
    await db.flush()
    return existing


async def ensure_system_roles_for_product(
    db: AsyncSession, *, product_id: UUID
) -> None:
    """Per-product system roles (owner / admin / member). Idempotent.

    Wraps in `bypass_product` so it works during product bootstrap before
    the request-level product context has been set.
    """
    perm_catalog = await ensure_permission_catalog(db)

    with bypass_product(), bypass_tenant():
        existing_roles = {
            r.name: r
            for r in (
                await db.scalars(
                    select(Role)
                    .options(selectinload(Role.permissions))
                    .where(Role.product_id == product_id, Role.tenant_id.is_(None))
                )
            ).all()
        }
        for name, perms in SYSTEM_ROLES.items():
            role = existing_roles.get(name)
            if role is None:
                role = Role(
                    name=name, is_system=True, tenant_id=None,
                    product_id=product_id, description=f"System role: {name}",
                )
                role.permissions = []  # avoid lazy-load on freshly-inserted row
                db.add(role)
                await db.flush()
            current = {rp.permission_id for rp in role.permissions}
            for code in perms:
                pid = perm_catalog[code].id
                if pid not in current:
                    db.add(RolePermission(role_id=role.id, permission_id=pid))
        await db.flush()


async def list_user_permission_codes(
    db: AsyncSession, user: User, *, tenant_id: UUID | None = None
) -> set[str]:
    """Return every permission code the user has *in the given tenant scope*.

    Honors `UserRole.scope_tenant_id`:
    - bindings with `scope_tenant_id IS NULL` apply in every tenant context
      (think: org-wide roles like owner / admin);
    - bindings with `scope_tenant_id = X` apply only when the request is
      acting in tenant X.

    If no `tenant_id` is passed, falls back to `current_tenant_id()` — the
    tenant the request is currently scoped to (which equals the user's home
    tenant on regular requests, or the child tenant when acting-as).
    """
    target_tid = tenant_id if tenant_id is not None else current_tenant_id()
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    if target_tid is not None:
        stmt = stmt.where(
            (UserRole.scope_tenant_id.is_(None)) | (UserRole.scope_tenant_id == target_tid)
        )
    else:
        stmt = stmt.where(UserRole.scope_tenant_id.is_(None))
    return set((await db.scalars(stmt)).all())


async def user_has_permission(
    db: AsyncSession, user: User, required: str, *, tenant_id: UUID | None = None
) -> bool:
    # Platform admin token short-circuit: a transient User created by
    # get_current_user from a valid X-Platform-Admin-Token has this flag set
    # and bypasses RBAC entirely (effective `*:*`). See dependencies.py.
    if getattr(user, "is_platform_admin", False):
        return True
    codes = await list_user_permission_codes(db, user, tenant_id=tenant_id)
    return any(_matches(g, required) for g in codes)


async def assign_role(
    db: AsyncSession,
    *,
    user_id: UUID,
    role_id: UUID,
    product_id: UUID,
    scope_tenant_id: UUID | None = None,
) -> UserRole:
    binding = UserRole(
        user_id=user_id, role_id=role_id,
        scope_tenant_id=scope_tenant_id, product_id=product_id,
    )
    db.add(binding)
    await db.flush()
    return binding


async def assign_role_by_name(
    db: AsyncSession, *, user: User, role_name: str
) -> UserRole:
    role = await db.scalar(
        select(Role).where(
            Role.name == role_name,
            Role.tenant_id.is_(None),
            Role.product_id == user.product_id,
        )
    )
    if role is None:
        raise RuntimeError(
            f"System role {role_name!r} missing for product {user.product_id} "
            "— run ensure_system_roles_for_product()."
        )
    return await assign_role(
        db, user_id=user.id, role_id=role.id, product_id=user.product_id,
    )


def expand_permissions(codes: Iterable[str]) -> set[str]:
    return set(codes)
