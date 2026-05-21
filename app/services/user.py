"""User lifecycle: invite, activate, deactivate, soft-delete.

Every user belongs to (product, tenant). The invite flow takes both —
typically the actor's product context.
"""

from datetime import UTC, datetime
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.core.security import hash_password
from app.models.role import Role, UserRole
from app.models.user import User
from app.services import audit


async def invite_user(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    email: str,
    full_name: str | None,
    role_codes: list[str],
    actor_user_id: UUID | None,
    initial_password: str | None = None,
) -> tuple[User, str]:
    """Create a tenant member. Returns (user, raw_password). The caller is
    responsible for surfacing the raw password to the inviter (we don't
    send transactional email yet)."""
    # Soft-deleted users still occupy a row but should not block re-invite
    # of the same email (the UNIQUE constraint is enforced via a partial
    # index `WHERE deleted_at IS NULL` — see scripts/migrate.py).
    existing = await db.scalar(
        select(User).where(
            User.tenant_id == tenant_id,
            User.email == email.lower(),
            User.deleted_at.is_(None),
        )
    )
    if existing:
        raise Conflict(f"user with email {email!r} already exists in tenant")

    # Short, copy-pastable random when admin doesn't pick one — easier to
    # share over Slack/IM than a 43-char token_urlsafe.
    raw_password = initial_password or token_urlsafe(12)
    user = User(
        product_id=product_id,
        tenant_id=tenant_id,
        email=email.lower(),
        password_hash=hash_password(raw_password),
        full_name=full_name,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()

    for code in role_codes or ["member"]:
        role = await db.scalar(
            select(Role).where(
                Role.name == code,
                Role.product_id == product_id,
                (Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)),
            )
        )
        if role is None:
            raise NotFound(f"role {code!r} not found in this product")
        db.add(UserRole(user_id=user.id, role_id=role.id, product_id=product_id))

    await audit.record(
        db, action="user.invite", actor_user_id=actor_user_id, resource_type="user",
        resource_id=user.id,
        diff={"email": email, "roles": role_codes, "password_supplied": initial_password is not None},
    )
    return user, raw_password


async def set_active(
    db: AsyncSession, *, user_id: UUID, active: bool, actor_user_id: UUID | None
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    user.is_active = active
    await audit.record(
        db,
        action="user.activate" if active else "user.deactivate",
        actor_user_id=actor_user_id,
        resource_type="user",
        resource_id=user.id,
        tenant_id=user.tenant_id,
        product_id=user.product_id,
    )
    return user


async def soft_delete(
    db: AsyncSession, *, user_id: UUID, actor_user_id: UUID | None
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFound("user not found")
    user.deleted_at = datetime.now(UTC)
    user.is_active = False
    await audit.record(
        db, action="user.delete", actor_user_id=actor_user_id, resource_type="user",
        resource_id=user.id, tenant_id=user.tenant_id, product_id=user.product_id,
    )
