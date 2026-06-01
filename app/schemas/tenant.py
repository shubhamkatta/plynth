from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.tenant import TenantStatus, TenantType
from app.schemas.common import TimestampedResponse


class TenantOwner(BaseModel):
    """Optional owner user to create atomically alongside the tenant.
    Admin-only bootstrap path — saves a follow-up call to invite + activate."""
    email:     EmailStr
    password:  str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class TenantCreate(BaseModel):
    name:       str = Field(min_length=1, max_length=255)
    slug:       str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    parent_id:  UUID | None = None
    type:       TenantType = TenantType.COMPANY
    settings:   dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    # Atomic bootstrap (admin-only). When provided, the new tenant gets an
    # owner user (with the system "owner" role) + a Subscription on
    # `plan_code` (or cheapest public plan) on trial. All in one
    # transaction — saves three round-trips for the common case.
    owner:      TenantOwner | None = None
    plan_code:  str | None = None


class TenantUpdate(BaseModel):
    # Reject unknown fields with 422 — silent drops mislead admins.
    model_config = ConfigDict(extra="forbid")

    name:       str | None = Field(default=None, min_length=1, max_length=255)
    # Slug renames are supported. The partial unique index on
    # (product_id, slug) WHERE deleted_at IS NULL prevents collisions
    # with live tenants — attempted reuse returns 409. URLs / external
    # bookmarks that hardcode the old slug WILL break; UUIDs (parent_id,
    # JWT tid claim) keep working since they don't reference slug.
    slug:       str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    settings:   dict[str, Any] | None = None
    # Admin override for the hard expiry cap. Pass null to clear, an ISO
    # datetime to extend / shorten. Enforced in app.core.dependencies.
    expires_at: datetime | None = None


class TenantResponse(TimestampedResponse):
    name:       str
    slug:       str
    status:     TenantStatus
    type:       TenantType
    parent_id:  UUID | None
    is_root:    bool
    settings:   dict[str, Any]
    expires_at: datetime | None


class AccessibleChildResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: TenantStatus
    can_act_as: bool
    reason: str | None
