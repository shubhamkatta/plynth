from uuid import UUID

from pydantic import BaseModel, Field

from app.models.tenant import TenantStatus, TenantType
from app.schemas.common import TimestampedResponse


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    parent_id: UUID | None = None
    settings: dict = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict | None = None


class TenantResponse(TimestampedResponse):
    name: str
    slug: str
    status: TenantStatus
    type: TenantType
    parent_id: UUID | None
    is_root: bool
    settings: dict


class AccessibleChildResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: TenantStatus
    can_act_as: bool
    reason: str | None
