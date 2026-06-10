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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Always 200 + this body — never leak whether the email exists.
    `reset_token` is populated only in non-production environments so
    dev/staging can test the flow without SMTP wired."""
    ok: bool = True
    reset_token: str | None = None
    expires_at: datetime | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=settings.password_min_length, max_length=128)


class GoogleLoginRequest(BaseModel):
    """OAuth2 authorization-code flow from the product's frontend.
    The frontend gets `code` from Google's redirect and forwards it
    here along with the same `redirect_uri` it used."""
    code: str = Field(min_length=10, max_length=2048)
    redirect_uri: str = Field(min_length=10, max_length=512)
    # Admin-set OAuth2 nonce check is out of scope — frontend should
    # verify the `state` round-trip on its side before calling us.


class MeResponse(BaseModel):
    id: UUID
    product_id: UUID
    tenant_id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_verified: bool
    permissions: list[str]
    # Map of active component code → whether the calling user has access.
    # Empty dict if the product has no components yet. Clients use this to
    # render conditionally without a second round-trip.
    components: dict[str, bool] = {}
