"""Product — the top of the entity tree.

A *Product* is one SaaS application (e.g. "ChatBot", "ImageGen"). Every
other entity (Tenant, User, Plan, Subscription, Credit, Audit…) is scoped
to exactly one Product. The same email / company / slug can exist
independently inside different products.

Products are created by platform admins (CLI / seed / `POST /admin/products`
with `X-Platform-Admin-Token`), not by end-users.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Enum, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPKMixin


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"   # API rejects all calls scoped to this product
    ARCHIVED = "archived"   # read-only, kept for billing/audit


class Product(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("slug", name="uq_products_slug"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, name="product_status"),
        default=ProductStatus.ACTIVE,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
