from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import CurrentUser, actor_id, require_permission
from app.core.exceptions import NotFound
from app.core.tenant import current_tenant_id
from app.models.invite import INVITE_KIND_JOIN_TENANT
from app.models.user import User
from app.schemas.invite import InviteCreate, InviteResponse
from app.schemas.user import InviteUserResponse, UserInvite, UserResponse, UserUpdate
from app.services import invite as invite_svc
from app.services import user as user_svc

router = APIRouter()


def _scoped_or_404(target: User | None, user: CurrentUser) -> User:
    tid = current_tenant_id() or user.tenant_id
    if (
        target is None
        or target.product_id != user.product_id
        or target.tenant_id != tid
    ):
        raise NotFound("user not found")
    return target


@router.get("", response_model=list[UserResponse],
            dependencies=[Depends(require_permission("users:read"))])
async def list_users(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[User]:
    tid = current_tenant_id() or user.tenant_id
    return list((await db.scalars(
        select(User).where(
            User.product_id == user.product_id,
            User.tenant_id == tid,
            User.deleted_at.is_(None),
        )
    )).all())


@router.post("", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("users:write"))])
async def invite(
    payload: UserInvite, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> InviteUserResponse:
    tid = current_tenant_id() or user.tenant_id
    new_user, password = await user_svc.invite_user(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        email=payload.email,
        full_name=payload.full_name,
        role_codes=payload.role_codes,
        actor_user_id=actor_id(user),
        initial_password=payload.initial_password,
    )
    return InviteUserResponse(
        id=new_user.id,
        created_at=new_user.created_at,
        updated_at=new_user.updated_at,
        tenant_id=new_user.tenant_id,
        email=new_user.email,
        full_name=new_user.full_name,
        is_active=new_user.is_active,
        is_verified=new_user.is_verified,
        initial_password=password,
    )


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("users:write"))])
async def create_invite(
    payload: InviteCreate, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> InviteResponse:
    """Email a tokenised invite for a teammate to join the caller's tenant.
    The invitee sets their own password via `POST /auth/invites/accept`."""
    tid = current_tenant_id() or user.tenant_id
    invite, link = await invite_svc.create_invite(
        db, product_id=user.product_id, kind=INVITE_KIND_JOIN_TENANT, tenant_id=tid,
        email=payload.email, full_name=payload.full_name, role_codes=payload.role_codes,
        plan_code=payload.plan_code, actor_user_id=actor_id(user),
        inviter_label=user.full_name or user.email,
    )
    return InviteResponse(
        id=invite.id, email=invite.email, kind=invite.kind, expires_at=invite.expires_at,
        link=None if settings.is_production else link,
    )


@router.patch("/{user_id}", response_model=UserResponse,
              dependencies=[Depends(require_permission("users:write"))])
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    target = _scoped_or_404(await db.get(User, user_id), actor)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(target, k, v)
    await db.flush()
    return target


@router.post("/{user_id}/activate", response_model=UserResponse,
             dependencies=[Depends(require_permission("users:activate"))])
async def activate(
    user_id: UUID, actor: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    _scoped_or_404(await db.get(User, user_id), actor)
    return await user_svc.set_active(db, user_id=user_id, active=True, actor_user_id=actor_id(actor))


@router.post("/{user_id}/deactivate", response_model=UserResponse,
             dependencies=[Depends(require_permission("users:activate"))])
async def deactivate(
    user_id: UUID, actor: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    _scoped_or_404(await db.get(User, user_id), actor)
    return await user_svc.set_active(db, user_id=user_id, active=False, actor_user_id=actor_id(actor))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("users:delete"))])
async def delete_user(
    user_id: UUID, actor: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    _scoped_or_404(await db.get(User, user_id), actor)
    await user_svc.soft_delete(db, user_id=user_id, actor_user_id=actor_id(actor))
