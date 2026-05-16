"""Platform-admin endpoints. Authenticated by `X-Platform-Admin-Token`
header (env var `PLATFORM_ADMIN_TOKEN`). These sit *above* products."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_platform_admin
from app.core.tenant import bypass_product, bypass_tenant
from app.schemas.product import ProductCreate, ProductResponse
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
    await product_svc.invalidate_slug_cache(product.slug)
    return product
