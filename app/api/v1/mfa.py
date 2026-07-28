from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser
from app.schemas.auth import TokenPair
from app.schemas.mfa import (
    MfaConfirmRequest,
    MfaDisableRequest,
    MfaEmailSetupResponse,
    MfaStatusResponse,
    MfaTotpSetupResponse,
    MfaVerifyRequest,
)
from app.services import mfa as mfa_svc

router = APIRouter()


@router.get("/status", response_model=MfaStatusResponse)
async def mfa_status(user: CurrentUser) -> MfaStatusResponse:
    return MfaStatusResponse(
        mfa_enabled=user.mfa_method is not None,
        mfa_method=user.mfa_method,
        mfa_enabled_at=user.mfa_enabled_at,
    )


@router.post("/totp/setup", response_model=MfaTotpSetupResponse)
async def setup_totp(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MfaTotpSetupResponse:
    secret, uri = await mfa_svc.setup_totp(db, user=user)
    return MfaTotpSetupResponse(secret=secret, provisioning_uri=uri)


@router.post("/email/setup", response_model=MfaEmailSetupResponse)
async def setup_email(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MfaEmailSetupResponse:
    await mfa_svc.setup_email(db, user=user)
    return MfaEmailSetupResponse()


@router.post("/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_setup(
    payload: MfaConfirmRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await mfa_svc.confirm_setup(db, user=user, method=payload.method, code=payload.code)


@router.post("/verify", response_model=TokenPair)
async def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    """Verify an MFA code during login. Accepts the ``mfa_token`` from
    the login response and returns a full token pair on success."""
    _, access, refresh, exp = await mfa_svc.verify_challenge(
        db,
        mfa_token=payload.mfa_token,
        code=payload.code,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disable_mfa(
    payload: MfaDisableRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await mfa_svc.disable_mfa(db, user=user, code=payload.code)
