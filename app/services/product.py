"""Product management.

Platform-admin operations (create / list / disable) plus a small in-process
+ Redis-backed slug→id resolver used by the request middleware.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.core.redis import get_redis
from app.models.product import Product, ProductStatus

SLUG_CACHE_KEY = "product:slug:{slug}"
SLUG_CACHE_TTL_SECONDS = 300


async def list_products(db: AsyncSession) -> list[Product]:
    return list(
        (await db.scalars(select(Product).where(Product.deleted_at.is_(None)))).all()
    )


async def get_by_slug(db: AsyncSession, slug: str) -> Product | None:
    result: Product | None = await db.scalar(
        select(Product).where(Product.slug == slug, Product.deleted_at.is_(None))
    )
    return result


async def get_or_404(db: AsyncSession, product_id: UUID) -> Product:
    p = await db.get(Product, product_id)
    if p is None or p.deleted_at is not None:
        raise NotFound(f"product {product_id} not found")
    return p


async def create_product(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    description: str | None = None,
    settings: dict[str, Any] | None = None,
) -> Product:
    if await get_by_slug(db, slug):
        raise Conflict(f"product slug {slug!r} already exists")
    product = Product(
        name=name, slug=slug, description=description,
        settings=settings or {}, status=ProductStatus.ACTIVE, is_active=True,
    )
    db.add(product)
    await db.flush()
    return product


async def resolve_slug_to_id(db: AsyncSession, slug: str) -> tuple[UUID, ProductStatus] | None:
    """Resolve a product slug to (id, status). Cached in Redis."""
    redis = get_redis()
    cached = await redis.get(SLUG_CACHE_KEY.format(slug=slug))
    if cached:
        data = json.loads(cached)
        return UUID(data["id"]), ProductStatus(data["status"])

    product = await get_by_slug(db, slug)
    if product is None:
        return None
    payload = json.dumps({"id": str(product.id), "status": product.status.value})
    await redis.set(SLUG_CACHE_KEY.format(slug=slug), payload, ex=SLUG_CACHE_TTL_SECONDS)
    return product.id, product.status


async def invalidate_slug_cache(slug: str) -> None:
    """Call after `create_product` / status changes so the resolver picks
    up the change."""
    await get_redis().delete(SLUG_CACHE_KEY.format(slug=slug))
