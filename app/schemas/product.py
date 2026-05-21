from pydantic import BaseModel, Field

from app.models.product import ProductStatus
from app.models.tenant import TenantType
from app.schemas.common import TimestampedResponse


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=512)
    settings: dict = Field(default_factory=dict)
    # Atomic bootstrap toggle: when True, the admin endpoint also seeds the
    # standard plan set for `tenant_type` in the same transaction so the
    # product is immediately usable. Idempotent — skips any plan whose code
    # already exists.
    seed_plans:  bool       = True
    tenant_type: TenantType = TenantType.COMPANY


class ProductResponse(TimestampedResponse):
    name: str
    slug: str
    description: str | None
    status: ProductStatus
    is_active: bool
    settings: dict
