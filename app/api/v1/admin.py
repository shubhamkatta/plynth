"""Platform-admin endpoints. Authenticated by `X-Platform-Admin-Token`
header (env var `PLATFORM_ADMIN_TOKEN`). These sit *above* products."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_platform_admin
from app.core.tenant import bypass_product, bypass_tenant
from app.core.exceptions import NotFound, ValidationFailed
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.services import plan as plan_svc
from app.services import product as product_svc
from app.services import rbac

router = APIRouter(dependencies=[Depends(require_platform_admin)])


@router.get("/products", response_model=list[ProductResponse])
async def list_products(db: Annotated[AsyncSession, Depends(get_db)]) -> list:
    with bypass_product(), bypass_tenant():
        return await product_svc.list_products(db)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> object:
    with bypass_product(), bypass_tenant():
        product = await product_svc.create_product(
            db, name=payload.name, slug=payload.slug,
            description=payload.description, settings=payload.settings,
        )
        # Seed the product's per-product system roles so registration works.
        await rbac.ensure_system_roles_for_product(db, product_id=product.id)
        if payload.seed_plans:
            await plan_svc.seed_standard_plans(
                db, product_id=product.id, tenant_type=payload.tenant_type,
            )
    await product_svc.invalidate_slug_cache(product.slug)
    return product


def _deep_merge(base: dict, patch: dict) -> dict:
    """Shallow per top-level key, deep one level down — enough for our
    settings tree (auth.*, features.*). Avoids dropping unrelated keys
    when a caller patches one sub-section."""
    out = {**base}
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


@router.patch("/products/{slug}", response_model=ProductResponse)
async def update_product(
    slug: str,
    payload: ProductUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Product:
    """Update fields on an existing product. `settings` is merged on top
    of the existing JSONB (keys not in the patch are preserved). Common
    use: configure per-product auth (`{"auth": {"refresh_ttl_days": 7}}`)
    or feature flags (`{"features": {"google_auto_provision": true}}`).
    """
    with bypass_product(), bypass_tenant():
        product = await product_svc.get_by_slug(db, slug)
        if product is None:
            raise NotFound(f"product {slug!r} not found")

        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationFailed("no fields to update")

        if "settings" in changes and changes["settings"] is not None:
            product.settings = _deep_merge(product.settings or {}, changes.pop("settings"))
        for k, v in changes.items():
            setattr(product, k, v)
        await db.flush()

    # Status changes invalidate the slug→id cache (resolver checks status).
    await product_svc.invalidate_slug_cache(product.slug)
    return product
