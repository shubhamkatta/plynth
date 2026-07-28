from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MfaTotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaEmailSetupResponse(BaseModel):
    message: str = "verification code sent"


class MfaConfirmRequest(BaseModel):
    method: Literal["totp", "email"]
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaDisableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaStatusResponse(BaseModel):
    mfa_enabled: bool
    mfa_method: str | None = None
    mfa_enabled_at: datetime | None = None
