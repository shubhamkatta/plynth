from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.config import settings


class InviteCreate(BaseModel):
    """Tenant-admin invite: a teammate joins the caller's tenant."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    role_codes: list[str] = Field(default_factory=list)
    plan_code: str | None = Field(default=None, max_length=64)


class ProspectInviteCreate(BaseModel):
    """Platform-admin invite: the invitee gets their OWN new tenant on accept."""
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    plan_code: str | None = Field(default=None, max_length=64)
    # False = create the invite and return the link WITHOUT emailing it, so the
    # admin can send it from their own mailbox (e.g. while SES is in sandbox).
    send_email: bool = True


class InviteResponse(BaseModel):
    id: UUID
    email: str
    kind: str
    expires_at: datetime
    # The accept link. Tenant-admin invites return it ONLY outside production
    # (the email is the proof the invitee controls the address). Platform-admin
    # prospect invites ALWAYS return it: the caller already holds the platform
    # admin token and is the one handing the link to the prospect.
    link: str | None = None


class InviteTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class InvitePreview(BaseModel):
    email: str
    full_name: str | None
    kind: str
    plan_code: str | None
    product_name: str
    expires_at: datetime


class InviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=settings.password_min_length, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
