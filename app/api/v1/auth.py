from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, RequireProduct
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterIndividualRequest,
    RegisterRequest,
    TokenPair,
)
from app.services import auth as auth_svc
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


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    request: Request,
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenPair:
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


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]) -> MeResponse:
    perms = await list_user_permission_codes(db, user)
    return MeResponse(
        id=user.id,
        product_id=user.product_id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        permissions=sorted(perms),
    )
