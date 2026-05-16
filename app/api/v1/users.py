from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.exceptions import NotFound
from app.core.tenant import current_tenant_id
from app.models.user import User
from app.schemas.user import UserInvite, UserResponse, UserUpdate
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


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("users:write"))])
async def invite(
    payload: UserInvite, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    tid = current_tenant_id() or user.tenant_id
    return await user_svc.invite_user(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        email=payload.email,
        full_name=payload.full_name,
        role_codes=payload.role_codes,
        actor_user_id=user.id,
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
    return await user_svc.set_active(db, user_id=user_id, active=True, actor_user_id=actor.id)


@router.post("/{user_id}/deactivate", response_model=UserResponse,
             dependencies=[Depends(require_permission("users:activate"))])
async def deactivate(
    user_id: UUID, actor: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    _scoped_or_404(await db.get(User, user_id), actor)
    return await user_svc.set_active(db, user_id=user_id, active=False, actor_user_id=actor.id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_permission("users:delete"))])
async def delete_user(
    user_id: UUID, actor: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    _scoped_or_404(await db.get(User, user_id), actor)
    await user_svc.soft_delete(db, user_id=user_id, actor_user_id=actor.id)
