"""Auth flows: register, login, refresh, logout, password change.

Every auth flow is scoped to a Product. `register` and `login` take an
explicit `product_id` from the route's `RequireProduct` dependency.
"""

from datetime import UTC, datetime
from uuid import UUID

import jwt
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_scope
from app.core.exceptions import Conflict, Unauthorized
from app.core.security import (
    decode_token,
    hash_password,
    issue_token,
    needs_rehash,
    verify_password,
)
from app.core.tenant import (
    bypass_product,
    bypass_tenant,
    set_current_product,
    set_current_tenant,
)
from app.models.tenant import Tenant
from app.models.user import RefreshToken, User
from app.services import audit, rbac, tenant as tenant_svc
from app.services.subscription import start_trial

log = structlog.get_logger("auth")


async def _audit_in_new_tx(**kwargs) -> None:
    """Write an audit entry in a fresh transaction so it survives the caller
    rolling back on exception (e.g. failed login)."""
    async with session_scope() as tx:
        await audit.record(tx, **kwargs)


async def register(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_name: str,
    tenant_slug: str,
    email: str,
    password: str,
    full_name: str | None,
) -> tuple[User, Tenant]:
    """Create a new root tenant + its owner user + a trial subscription
    in the given product."""
    tenant = await tenant_svc.create_tenant(
        db, product_id=product_id, name=tenant_name, slug=tenant_slug,
    )
    set_current_product(product_id)
    set_current_tenant(tenant.id)

    user = User(
        product_id=product_id,
        tenant_id=tenant.id,
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()

    await rbac.ensure_system_roles_for_product(db, product_id=product_id)
    await rbac.assign_role_by_name(db, user=user, role_name="owner")
    await start_trial(db, tenant_id=tenant.id, product_id=product_id)
    await audit.record(
        db,
        action="user.register",
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        diff={"email": email},
    )
    return user, tenant


async def login(
    db: AsyncSession,
    *,
    product_id: UUID,
    email: str,
    password: str,
    tenant_slug: str | None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str, datetime]:
    """Verify credentials, issue access + refresh tokens."""
    with bypass_product(), bypass_tenant():
        stmt = (
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(User.email == email.lower(), User.product_id == product_id)
        )
        if tenant_slug:
            stmt = stmt.where(Tenant.slug == tenant_slug)
        user = await db.scalar(stmt)

    if user is None or not user.is_active:
        log.warning(
            "login.failed", email=email, reason="user_missing_or_inactive",
            ip=ip_address, product_id=str(product_id),
        )
        if user is not None:
            await _audit_in_new_tx(
                action="user.login_failed", actor_user_id=user.id,
                actor_ip=ip_address, resource_type="user", resource_id=user.id,
                tenant_id=user.tenant_id, product_id=user.product_id,
                diff={"reason": "inactive_user"},
            )
        raise Unauthorized("invalid credentials")
    if not verify_password(password, user.password_hash):
        log.warning(
            "login.failed", email=email, reason="bad_password",
            ip=ip_address, product_id=str(product_id),
        )
        await _audit_in_new_tx(
            action="user.login_failed", actor_user_id=user.id,
            actor_ip=ip_address, resource_type="user", resource_id=user.id,
            tenant_id=user.tenant_id, product_id=user.product_id,
            diff={"reason": "bad_password"},
        )
        raise Unauthorized("invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    set_current_product(user.product_id)
    set_current_tenant(user.tenant_id)
    access_token, _, access_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="access",
    )
    refresh_token, jti, refresh_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="refresh",
    )
    db.add(
        RefreshToken(
            product_id=user.product_id,
            user_id=user.id,
            jti=jti,
            expires_at=refresh_exp,
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )
    user.last_login_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db, action="user.login", actor_user_id=user.id, resource_type="user",
        resource_id=user.id, actor_ip=ip_address,
    )
    return user, access_token, refresh_token, access_exp


async def refresh(
    db: AsyncSession, *, refresh_token: str
) -> tuple[User, str, str, datetime]:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"invalid refresh token: {exc}") from exc

    jti = payload["jti"]
    user_id = UUID(payload["sub"])

    record = await db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if record is None or record.revoked_at is not None or record.expires_at <= datetime.now(UTC):
        raise Unauthorized("refresh token revoked or expired")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("user inactive")

    # Rotate: revoke old, issue new.
    record.revoked_at = datetime.now(UTC)
    set_current_product(user.product_id)
    set_current_tenant(user.tenant_id)
    access_token, _, access_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="access",
    )
    new_refresh, new_jti, new_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="refresh",
    )
    db.add(RefreshToken(
        product_id=user.product_id, user_id=user.id, jti=new_jti, expires_at=new_exp,
    ))
    await db.flush()
    return user, access_token, new_refresh, access_exp


async def logout(
    db: AsyncSession,
    *,
    user: User,
    refresh_token: str | None,
    all_sessions: bool,
) -> None:
    now = datetime.now(UTC)
    if all_sessions:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    elif refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except jwt.PyJWTError:
            return
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.jti == payload["jti"], RefreshToken.user_id == user.id)
            .values(revoked_at=now)
        )
    await audit.record(
        db, action="user.logout", actor_user_id=user.id, resource_type="user",
        resource_id=user.id, diff={"all_sessions": all_sessions},
    )


async def change_password(
    db: AsyncSession, *, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise Unauthorized("current password incorrect")
    if current_password == new_password:
        raise Conflict("new password must differ from current")
    user.password_hash = hash_password(new_password)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await audit.record(
        db, action="user.password_change", actor_user_id=user.id, resource_type="user",
        resource_id=user.id,
    )
