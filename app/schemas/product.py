from typing import Any

from pydantic import BaseModel, Field

from app.models.product import ProductStatus
from app.models.tenant import TenantType
from app.schemas.common import TimestampedResponse


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=512)
    settings: dict[str, Any] = Field(default_factory=dict)
    # Atomic bootstrap toggle: when True, the admin endpoint also seeds the
    # standard plan set for `tenant_type` in the same transaction so the
    # product is immediately usable. Idempotent — skips any plan whose code
    # already exists.
    seed_plans:  bool       = True
    tenant_type: TenantType = TenantType.COMPANY


class ProductUpdate(BaseModel):
    """Mutate an existing product. `settings` is shallow-merged on top
    of the existing JSONB so partial patches don't wipe unrelated keys
    — e.g. updating `auth.refresh_ttl_days` leaves `features.*` alone."""
    name:        str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    status:      ProductStatus | None = None
    is_active:   bool | None = None
    settings:    dict[str, Any] | None = None


class ProductResponse(TimestampedResponse):
    name: str
    slug: str
    description: str | None
    status: ProductStatus
    is_active: bool
    settings: dict[str, Any]
