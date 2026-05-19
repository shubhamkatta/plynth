from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=settings.password_min_length, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class RegisterIndividualRequest(BaseModel):
    """B2C signup. No tenant_name / tenant_slug — the platform derives them.
    Creates a private "tenant of 1" with `type=individual`."""
    email: EmailStr
    password: str = Field(min_length=settings.password_min_length, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = None  # optional for multi-tenant disambiguation


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=settings.password_min_length, max_length=128)


class MeResponse(BaseModel):
    id: UUID
    product_id: UUID
    tenant_id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_verified: bool
    permissions: list[str]
