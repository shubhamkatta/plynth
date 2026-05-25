"""Repository base classes.

`TenantRepository` automatically injects the (product_id, tenant_id) filter
from the request context. Bypass requires explicit `bypass_product()` /
`bypass_tenant()`. See docs/multi-tenancy.md + docs/multi-product.md.
"""

from typing import Any, Generic, TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.core.tenant import (
    current_product_id,
    current_tenant_id,
    is_bypass,
    is_product_bypass,
)
from app.models.base import Base  # noqa: F401  (re-exported for callers)

ModelT = TypeVar("ModelT", bound=Base)


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def get_or_404(self, id_: UUID) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFound(f"{self.model.__name__} {id_} not found")
        return obj

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()


# Concrete tenant-scoped models inherit both `Base` and `TenantScopedMixin`
# (and usually `ProductScopedMixin`); the `Base` bound is what the parent
# `Repository[ModelT]` requires. The mixin attributes (`tenant_id`,
# optionally `product_id`) are detected at runtime via `hasattr`.
TenantModelT = TypeVar("TenantModelT", bound=Base)


class TenantRepository(Repository[TenantModelT]):
    """Auto-scopes every read and write to (current product, current tenant).

    A model is considered product-scoped if it exposes a `product_id`
    attribute (i.e. inherits `ProductScopedMixin`). Same for `tenant_id`.
    """

    def _stmt(self) -> Select[Any]:
        stmt: Select[Any] = select(self.model)
        if hasattr(self.model, "product_id") and not is_product_bypass():
            pid = current_product_id()
            if pid is None:
                raise RuntimeError(
                    f"{self.model.__name__} repository used without an active product "
                    "context. Set one via the product dependency or wrap in bypass_product()."
                )
            stmt = stmt.where(self.model.product_id == pid)  # type: ignore[attr-defined]
        if hasattr(self.model, "tenant_id") and not is_bypass():
            tid = current_tenant_id()
            if tid is None:
                raise RuntimeError(
                    f"{self.model.__name__} repository used without an active tenant "
                    "context. Set one via dependencies or wrap in bypass_tenant()."
                )
            stmt = stmt.where(self.model.tenant_id == tid)  # type: ignore[attr-defined]
        return stmt

    async def get(self, id_: UUID) -> TenantModelT | None:
        stmt = self._stmt().where(self.model.id == id_)  # type: ignore[attr-defined]
        return cast(TenantModelT | None, await self.session.scalar(stmt))

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[TenantModelT]:
        stmt = self._stmt().limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all())

    async def add(self, obj: TenantModelT) -> TenantModelT:
        # `TenantModelT` is bound to `Base`; the mixin-supplied columns are
        # only known at runtime, so reach for `getattr` / `setattr` to keep
        # the strict type checker quiet without losing the safety net.
        if hasattr(obj, "product_id") and not is_product_bypass():
            pid = current_product_id()
            if pid is None:
                raise RuntimeError("Cannot add product-scoped row without product context.")
            existing_pid = getattr(obj, "product_id", None)
            if existing_pid is None:
                # B010: setattr-with-literal — required here because the
                # column comes from a mixin and isn't on the TypeVar bound.
                setattr(obj, "product_id", pid)  # noqa: B010
            elif existing_pid != pid:
                raise RuntimeError("product_id on object does not match current product context.")
        if not is_bypass():
            tid = current_tenant_id()
            if tid is None:
                raise RuntimeError("Cannot add tenant-scoped row without tenant context.")
            existing_tid = getattr(obj, "tenant_id", None)
            if existing_tid is None:
                setattr(obj, "tenant_id", tid)  # noqa: B010
            elif existing_tid != tid:
                raise RuntimeError("tenant_id on object does not match current tenant context.")
        return await super().add(obj)
