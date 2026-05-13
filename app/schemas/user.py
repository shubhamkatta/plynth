from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings
from app.schemas.common import TimestampedResponse


class UserInvite(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    role_codes: list[str] = Field(default_factory=list)
    scope_tenant_id: UUID | None = None


class UserCreateAdmin(UserInvite):
    password: str = Field(min_length=settings.password_min_length, max_length=128)


class UserUpdate(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None


class UserResponse(TimestampedResponse):
    tenant_id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_verified: bool
