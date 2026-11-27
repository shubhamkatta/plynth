"""A product selects its role template by settings, not by its slug.

`PRODUCT_SYSTEM_ROLES` used to be keyed on the product slug alone, which tied
a platform-level template to one deployment's public identifier: the template
had to be *named* after the product, two products of the same kind had to
duplicate it, and renaming a product silently stopped its staff roles being
seeded. `ensure_system_roles_for_product` runs on **every registration**, so
that last failure mode is quiet and expensive — new users would simply arrive
with only owner/admin/member.

So the template is now chosen by `Product.settings.rbac.system_roles_template`,
falling back to the slug. These pin all three paths, because the fallback is
what keeps existing products working and the selection is what lets a product
be named anything.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import session_scope
from app.core.tenant import bypass_product, bypass_tenant
from app.models.product import Product, ProductStatus
from app.models.role import Role
from app.services import rbac

TEMPLATE_ROLES = {"practitioner", "assistant", "clinic_admin", "patient"}
SHARED_ROLES = {"owner", "admin", "member"}


async def _make_product(*, slug: str, settings: dict | None = None) -> Product:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = Product(
                name=f"Template Test {uuid4().hex[:6]}",
                slug=slug,
                status=ProductStatus.ACTIVE,
                is_active=True,
                settings=settings or {},
            )
            db.add(product)
            await db.flush()
            await rbac.ensure_system_roles_for_product(db, product_id=product.id)
            return product


async def _role_names(product_id) -> set[str]:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            rows = (
                await db.scalars(
                    select(Role)
                    .options(selectinload(Role.permissions))
                    .where(Role.product_id == product_id, Role.tenant_id.is_(None))
                )
            ).all()
            return {r.name for r in rows}


@pytest.mark.asyncio
async def test_settings_select_the_template_for_any_slug() -> None:
    """The case production depends on: a product whose slug says nothing about
    its template still gets the template's roles."""
    product = await _make_product(
        slug=f"anything-{uuid4().hex[:8]}",
        settings={"rbac": {"system_roles_template": "acme-practice"}},
    )
    names = await _role_names(product.id)
    assert TEMPLATE_ROLES <= names, f"template roles missing: {TEMPLATE_ROLES - names}"
    assert SHARED_ROLES <= names


@pytest.mark.asyncio
async def test_the_slug_still_works_as_a_fallback() -> None:
    """Products that predate the settings key keep their roles with no data
    migration — the fallback is the whole reason this is safe to ship."""
    product = await _make_product(slug=f"acme-practice-{uuid4().hex[:6]}")
    names = await _role_names(product.id)
    # This slug is NOT the template key, so only the shared roles apply.
    assert names == SHARED_ROLES

    exact = await _make_product(slug="acme-practice-fallback-check")
    assert await _role_names(exact.id) == SHARED_ROLES


@pytest.mark.asyncio
async def test_an_exact_slug_match_needs_no_settings() -> None:
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            existing = await db.scalar(
                select(Product).where(Product.slug == "acme-practice")
            )
            if existing is None:
                existing = Product(
                    name="Acme Slug Fallback", slug="acme-practice",
                    status=ProductStatus.ACTIVE, is_active=True,
                )
                db.add(existing)
                await db.flush()
            await rbac.ensure_system_roles_for_product(db, product_id=existing.id)
            pid = existing.id
    assert TEMPLATE_ROLES <= await _role_names(pid)


@pytest.mark.asyncio
async def test_an_unknown_template_means_no_extra_roles() -> None:
    """A typo, or a product that genuinely has no staff roles, must degrade to
    the shared set rather than raise during a registration."""
    product = await _make_product(
        slug=f"plain-{uuid4().hex[:8]}",
        settings={"rbac": {"system_roles_template": "no-such-template"}},
    )
    assert await _role_names(product.id) == SHARED_ROLES


@pytest.mark.asyncio
async def test_settings_without_an_rbac_block_are_fine() -> None:
    """`settings` is free-form JSON used for app_url, features and auth too.
    An absent `rbac` key must not be an error."""
    product = await _make_product(
        slug=f"nosettings-{uuid4().hex[:8]}",
        settings={"app_url": "https://app.example.com"},
    )
    assert await _role_names(product.id) == SHARED_ROLES
