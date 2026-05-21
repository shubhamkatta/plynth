from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings
from app.schemas.common import TimestampedResponse


class UserInvite(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    role_codes: list[str] = Field(default_factory=list)
    scope_tenant_id: UUID | None = None
    # Optional admin-set password. When omitted, a strong random one is
    # generated server-side. Either way, the password is returned ONCE in
    # InviteUserResponse so the admin can share it out-of-band (no
    # transactional email is wired yet).
    initial_password: str | None = Field(
        default=None, min_length=settings.password_min_length, max_length=128,
    )


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


class InviteUserResponse(UserResponse):
    """Returned only from POST /users. Carries the one-shot password so the
    inviter can share it out-of-band. Never persisted in plaintext, never
    returned from subsequent reads."""
    initial_password: str
