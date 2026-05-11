"""Declarative base, mixins, common column types."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, MetaData
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
)

# Naming convention so Alembic generates stable constraint names.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class UUIDPKMixin:
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    # Python-side defaults + onupdate avoid server-side RETURNING dance that
    # triggers MissingGreenlet when the model is re-serialised after a flush.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class ProductScopedMixin:
    """Adds `product_id` FK. Every domain table that is owned by a single
    product carries this column for direct filtering. See docs/multi-product.md.
    """

    @declared_attr
    @classmethod
    def product_id(cls) -> Mapped[UUID]:
        return mapped_column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class TenantScopedMixin:
    """Adds `tenant_id` FK. The query-time tenant filter is applied by
    `app.repositories.base.TenantRepository`. See docs/multi-tenancy.md.

    Models that are tenant-scoped are also product-scoped — mix in
    `ProductScopedMixin` as well so the repository can apply the dual
    `(product_id, tenant_id)` filter.
    """

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            PG_UUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
