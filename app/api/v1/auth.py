from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import CurrentUser, RequireProduct
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleLoginRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    MfaChallengeRequired,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterIndividualRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
)
from app.schemas.invite import InviteAccept, InvitePreview, InviteTokenRequest
from app.services import auth as auth_svc
from app.services import component as component_svc
from app.services import invite as invite_svc
from app.services import mfa as mfa_svc
from app.services.rbac import list_user_permission_codes

router = APIRouter()


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    await auth_svc.register(
        db,
        product_id=product_id,
        tenant_name=payload.tenant_name,
        tenant_slug=payload.tenant_slug,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )
    _, access, refresh, exp = await auth_svc.login(
        db,
        product_id=product_id,
        email=payload.email,
        password=payload.password,
        tenant_slug=payload.tenant_slug,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.post(
    "/register-individual",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="B2C signup — creates a private tenant of 1",
)
async def register_individual(
    payload: RegisterIndividualRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
    """Convenience endpoint for products whose customer is an individual,
    not a company. No tenant_name / tenant_slug required — the platform
    derives them. Under the hood it's a normal register with
    `type=individual`, so everything (subscription, credits, audit) works
    identically. The user can later invite teammates if they want."""
    await auth_svc.register_individual(
        db,
        product_id=product_id,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )
    _, access, refresh, exp = await auth_svc.login(
        db,
        product_id=product_id,
        email=payload.email,
        password=payload.password,
        tenant_slug=None,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair | MfaChallengeRequired:
    user = await auth_svc.verify_credentials(
        db,
        product_id=product_id,
        email=payload.email,
        password=payload.password,
        tenant_slug=payload.tenant_slug,
        ip_address=request.client.host if request.client else None,
    )
    if user.mfa_method:
        return await mfa_svc.create_challenge(db, user=user)
    _, access, refresh, exp = await auth_svc.complete_login(
        db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.post("/invites/preview", response_model=InvitePreview)
async def preview_invite(
    payload: InviteTokenRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> InvitePreview:
    """Public. Lets the accept page show who/what the invite is for. POST (not
    GET) so the token never lands in URLs/access logs."""
    invite, product_name = await invite_svc.preview(db, raw=payload.token)
    return InvitePreview(
        email=invite.email, full_name=invite.full_name, kind=invite.kind,
        plan_code=invite.plan_code, product_name=product_name,
        expires_at=invite.expires_at,
    )


@router.post("/invites/accept", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    payload: InviteAccept, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    """Public. Consumes a single-use invite, creates the account with the
    chosen password, and signs the user in."""
    access, refresh, exp = await invite_svc.accept(
        db, raw=payload.token, password=payload.password, full_name=payload.full_name,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    _, access, refresh, exp = await auth_svc.refresh(db, refresh_token=payload.refresh_token)
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await auth_svc.logout(
        db, user=user, refresh_token=payload.refresh_token, all_sessions=payload.all_sessions
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await auth_svc.change_password(
        db, user=user, current_password=payload.current_password, new_password=payload.new_password
    )


@router.post("/password/forgot", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ForgotPasswordResponse:
    """Always returns 200 with ok=true — never leaks whether the email
    exists. In non-production environments the response carries the raw
    token so dev/staging can test the flow without SMTP wired.

    Production: route the token into a transactional-email provider in
    `app/providers/notifications.py` (currently a stub) and build the
    public reset link as `<product_app_url>/reset?token=<token>`."""
    raw, expires = await auth_svc.request_password_reset(
        db, product_id=product_id, email=payload.email,
        ip_address=request.client.host if request.client else None,
    )
    if raw is not None:
        await auth_svc.send_password_reset_email(
            db, product_id=product_id, email=payload.email, raw_token=raw
        )
    if raw is not None and not settings.is_production:
        return ForgotPasswordResponse(reset_token=raw, expires_at=expires)
    return ForgotPasswordResponse()


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Consumes a forgot-password token, updates the password, and
    revokes every existing refresh token so old sessions can't continue."""
    await auth_svc.confirm_password_reset(
        db, token=payload.token, new_password=payload.new_password,
    )


@router.post("/google")
async def login_google(
    payload: GoogleLoginRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair | MfaChallengeRequired:
    """OAuth2 authorization-code login.

    Frontend flow:
    1. Redirect user to `https://accounts.google.com/o/oauth2/v2/auth`
       with this product's `client_id`, the `redirect_uri` it'll handle,
       `scope=openid email profile`, and a `state` nonce.
    2. Google redirects back to `redirect_uri` with `code` + `state`.
    3. Frontend verifies `state`, then POSTs {code, redirect_uri} here.

    Returns the standard TokenPair on success. If MFA is enabled for the
    user, returns an MfaChallengeRequired instead — the client must then
    verify the code at POST /auth/mfa/verify."""
    user, google_ctx = await auth_svc.verify_google_credentials(
        db,
        product_id=product_id,
        code=payload.code,
        redirect_uri=payload.redirect_uri,
        ip_address=request.client.host if request.client else None,
    )
    if user.mfa_method:
        return await mfa_svc.create_challenge(db, user=user)
    _, access, refresh, exp = await auth_svc.complete_login(
        db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
        audit_action="user.login_google",
        audit_diff=google_ctx,
    )
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=exp)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]) -> MeResponse:
    perms = await list_user_permission_codes(db, user)
    component_rows = await component_svc.user_effective_components(db, user=user)
    components = {c.code: is_enabled for (c, is_enabled, _src, _reason) in component_rows}
    return MeResponse(
        id=user.id,
        product_id=user.product_id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        permissions=sorted(perms),
        mfa_enabled=user.mfa_method is not None,
        mfa_method=user.mfa_method,
        components=components,
    )
