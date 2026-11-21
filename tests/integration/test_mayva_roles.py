"""Mayva-scoped system role seeding (rbac.PRODUCT_SYSTEM_ROLES["mayva-practice"]).

Asserts the per-product staff roles seed under a `mayva`-slugged product with
exactly their intended permission sets. In particular the `patient` role — an
end-patient provisioned as a plynth user — must be DELIBERATELY NARROW: it may
read only its own portal and book its own appointments, and must NOT be able to
touch other patients, clinical notes, sessions, the inbox, payments, audit,
availability internals, or any practice/admin surface.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.permission import Permission
from app.models.product import Product, ProductStatus
from app.models.role import Role
from app.services import rbac


async def _seed_mayva_roles() -> Product:
    """Ensure a `mayva-practice`-slugged product exists and (re)seed its roles.

    Slug must be exactly "mayva-practice" for PRODUCT_SYSTEM_ROLES to apply.
    Products are preserved across tests (CATALOG_TABLES) and `slug` is unique,
    so this reuses the product if a prior test already created it — the seed
    itself is idempotent.
    """
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                select(Product).where(Product.slug == "mayva-practice")
            )
            if product is None:
                product = Product(
                    name=f"Mayva Roles Test {uuid4().hex[:6]}", slug="mayva-practice",
                    status=ProductStatus.ACTIVE, is_active=True,
                )
                db.add(product)
                await db.flush()
            await rbac.ensure_system_roles_for_product(db, product_id=product.id)
    return product


async def _role_perm_codes(product_id, name: str) -> set[str]:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            role = await db.scalar(
                select(Role)
                .options(selectinload(Role.permissions))
                .where(
                    Role.product_id == product_id,
                    Role.tenant_id.is_(None),
                    Role.name == name,
                )
            )
            if role is None:
                return set()
            perm_ids = [rp.permission_id for rp in role.permissions]
            codes = (
                await db.scalars(
                    select(Permission.code).where(Permission.id.in_(perm_ids))
                )
            ).all()
            return set(codes)


@pytest.mark.asyncio
async def test_patient_role_seeds_with_exactly_two_permissions() -> None:
    product = await _seed_mayva_roles()
    codes = await _role_perm_codes(product.id, "patient")
    # Exactly these two — nothing more.
    assert codes == {"portal:read", "booking:create"}


@pytest.mark.asyncio
async def test_patient_role_has_no_clinical_or_admin_access() -> None:
    product = await _seed_mayva_roles()
    codes = await _role_perm_codes(product.id, "patient")
    forbidden_prefixes = (
        "client:", "note:", "session:", "inbox:", "payment:",
        "audit:", "availability:", "approval:", "gdpr:", "digest:",
        "settings:", "users:", "roles:", "tenants:",
    )
    leaked = {c for c in codes for p in forbidden_prefixes if c.startswith(p)}
    assert leaked == set(), f"patient role leaked forbidden permissions: {leaked}"
    assert "*:*" not in codes


@pytest.mark.asyncio
async def test_patient_role_is_system_and_product_scoped() -> None:
    product = await _seed_mayva_roles()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            role = await db.scalar(
                select(Role).where(
                    Role.product_id == product.id,
                    Role.tenant_id.is_(None),
                    Role.name == "patient",
                )
            )
    assert role is not None
    assert role.is_system is True
    assert role.tenant_id is None
    assert role.product_id == product.id


@pytest.mark.asyncio
async def test_mayva_staff_roles_seed_alongside_patient() -> None:
    """practitioner / assistant still seed with their full sets, and every
    product also gets owner / admin / member."""
    product = await _seed_mayva_roles()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            names = set(
                (
                    await db.scalars(
                        select(Role.name).where(
                            Role.product_id == product.id,
                            Role.tenant_id.is_(None),
                        )
                    )
                ).all()
            )
    assert {"owner", "admin", "member", "practitioner", "assistant", "patient"}.issubset(names)


@pytest.mark.asyncio
async def test_patient_role_seed_is_idempotent() -> None:
    """Re-running the seed does not duplicate the patient role's permissions."""
    product = await _seed_mayva_roles()
    # Run again against the same product.
    async with session_scope() as db:
        await rbac.ensure_system_roles_for_product(db, product_id=product.id)
    codes = await _role_perm_codes(product.id, "patient")
    assert codes == {"portal:read", "booking:create"}

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            role = await db.scalar(
                select(Role)
                .options(selectinload(Role.permissions))
                .where(
                    Role.product_id == product.id,
                    Role.tenant_id.is_(None),
                    Role.name == "patient",
                )
            )
    # Two RolePermission rows exactly — no duplicates from the second run.
    assert len(role.permissions) == 2


@pytest.mark.asyncio
async def test_mayva_permission_catalog_covers_every_code_the_backend_requires() -> None:
    """The 28 codes Mayva's backend gates on (swept from its require_permission
    calls) must all exist in the global catalog, or non-owner users 403 on them."""
    mayva_codes = {
        "settings:manage", "client:read", "session:read", "client:update",
        "availability:manage", "subscriptions:read", "staff:manage", "session:update",
        "payment:manage", "payment:read", "note:read", "note:create", "client:create",
        "availability:read", "approval:decide", "alert:read", "subscriptions:change",
        "session:create", "portal:read", "note:sign", "inbox:send", "analytics:read",
        "message:read", "inbox:read", "gdpr:export", "gdpr:erase", "digest:read",
        "dashboard:read",
    }
    assert len(mayva_codes) == 28
    catalog = {c for c, _ in rbac.SYSTEM_PERMISSIONS}
    assert mayva_codes - catalog == set()


@pytest.mark.asyncio
async def test_practitioner_gets_dashboard_and_analytics_but_not_staff_manage() -> None:
    product = await _seed_mayva_roles()
    prac = await _role_perm_codes(product.id, "practitioner")
    assert {"dashboard:read", "analytics:read", "alert:read", "message:read",
            "subscriptions:read"} <= prac
    # Managing colleagues is an owner/admin function.
    assert "staff:manage" not in prac
    # ...and the practitioner still cannot manage practice settings or billing.
    assert "settings:manage" not in prac and "subscriptions:change" not in prac


@pytest.mark.asyncio
async def test_admin_and_owner_can_manage_staff() -> None:
    product = await _seed_mayva_roles()
    assert "staff:manage" in await _role_perm_codes(product.id, "admin")
    # owner holds *:* which matches any code
    assert any(rbac._matches(g, "staff:manage") for g in rbac.SYSTEM_ROLES["owner"])
    # assistant / patient must not
    assert "staff:manage" not in await _role_perm_codes(product.id, "assistant")
    assert "staff:manage" not in await _role_perm_codes(product.id, "patient")


CLINIC_ADMIN = {
    "settings:manage", "staff:manage", "subscriptions:read", "subscriptions:change",
    "payment:read", "payment:manage", "availability:read", "availability:manage",
    "client:read", "client:create", "client:update", "dashboard:read",
    "analytics:read", "digest:read", "alert:read",
}


@pytest.mark.asyncio
async def test_clinic_admin_role_has_exactly_the_agreed_permissions() -> None:
    product = await _seed_mayva_roles()
    assert await _role_perm_codes(product.id, "clinic_admin") == CLINIC_ADMIN


@pytest.mark.asyncio
async def test_clinic_admin_cannot_touch_special_category_data() -> None:
    """An office manager must not read session notes or message bodies, speak as
    the therapist, approve AI drafts, or export/erase personal data."""
    product = await _seed_mayva_roles()
    codes = await _role_perm_codes(product.id, "clinic_admin")
    forbidden = {"note:read", "note:create", "note:sign", "message:read", "inbox:send",
                 "inbox:read", "approval:decide", "gdpr:export", "gdpr:erase",
                 "session:read", "session:update", "session:create", "*:*"}
    assert codes & forbidden == set()
    assert not any(c.startswith("note:") or c.startswith("gdpr:") for c in codes)


@pytest.mark.asyncio
async def test_clinic_admin_seed_is_idempotent_and_distinct_from_admin() -> None:
    product = await _seed_mayva_roles()
    async with session_scope() as db:
        await rbac.ensure_system_roles_for_product(db, product_id=product.id)
    assert await _role_perm_codes(product.id, "clinic_admin") == CLINIC_ADMIN
    # plynth's own `admin` is unchanged by this role (no settings/clinical access).
    admin = await _role_perm_codes(product.id, "admin")
    assert "settings:manage" not in admin and "client:read" not in admin
