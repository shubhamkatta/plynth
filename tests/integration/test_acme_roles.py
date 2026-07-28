"""Acme-scoped system role seeding (rbac.PRODUCT_SYSTEM_ROLES["acme"]).

Asserts the per-product staff roles seed under a `acme`-slugged product with
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


async def _seed_acme_roles() -> Product:
    """Ensure a `acme`-slugged product exists and (re)seed its system roles.

    Slug must be exactly "acme" for PRODUCT_SYSTEM_ROLES to apply. Products
    are preserved across tests (CATALOG_TABLES) and `slug` is unique, so this
    reuses the product if a prior test already created it — the seed itself is
    idempotent.
    """
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                select(Product).where(Product.slug == "acme")
            )
            if product is None:
                product = Product(
                    name=f"Acme Roles Test {uuid4().hex[:6]}", slug="acme",
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
    product = await _seed_acme_roles()
    codes = await _role_perm_codes(product.id, "patient")
    # Exactly these two — nothing more.
    assert codes == {"portal:read", "booking:create"}


@pytest.mark.asyncio
async def test_patient_role_has_no_clinical_or_admin_access() -> None:
    product = await _seed_acme_roles()
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
    product = await _seed_acme_roles()
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
async def test_acme_staff_roles_seed_alongside_patient() -> None:
    """practitioner / assistant still seed with their full sets, and every
    product also gets owner / admin / member."""
    product = await _seed_acme_roles()
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
    product = await _seed_acme_roles()
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
