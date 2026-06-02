"""Auth flows: register, login, refresh, logout, password change.

Every auth flow is scoped to a Product. `register` and `login` take an
explicit `product_id` from the route's `RequireProduct` dependency.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

import jwt
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import session_scope
from app.core.exceptions import Conflict, NotFound, Unauthorized
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
from app.models.product import Product
from app.models.tenant import Tenant, TenantType
from app.models.user import PasswordResetToken, RefreshToken, User
from app.services import audit, rbac
from app.services import tenant as tenant_svc
from app.services.subscription import start_trial

log = structlog.get_logger("auth")


async def _refresh_ttl_seconds(db: AsyncSession, product_id: UUID) -> int:
    """Per-product refresh-token TTL. Reads
    `Product.settings.auth.refresh_ttl_days` if set, otherwise falls back
    to the platform-wide `JWT_REFRESH_TTL_SECONDS` (30 days by default).

    Bounded to [1 day, 365 days] to prevent typos from creating tokens
    that effectively never expire or expire immediately."""
    with bypass_product(), bypass_tenant():
        product = await db.get(Product, product_id)
    if product is not None:
        days = (product.settings or {}).get("auth", {}).get("refresh_ttl_days")
        if isinstance(days, int) and 1 <= days <= 365:
            return days * 86400
    return settings.jwt_refresh_ttl_seconds


async def _audit_in_new_tx(**kwargs: Any) -> None:
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
    tenant_type: TenantType = TenantType.COMPANY,
) -> tuple[User, Tenant]:
    """Create a new root tenant + its owner user + a trial subscription
    in the given product."""
    tenant = await tenant_svc.create_tenant(
        db, product_id=product_id, name=tenant_name, slug=tenant_slug, type=tenant_type,
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
        diff={"email": email, "tenant_type": tenant_type.value},
    )
    return user, tenant


def _derive_individual_slug() -> str:
    """`usr-` + 8 hex chars from uuid4. Collisions in production are
    handled by the unique constraint on (product_id, slug) — the caller
    retries with a fresh slug."""
    return f"usr-{uuid4().hex[:8]}"


def _derive_individual_name(email: str, full_name: str | None) -> str:
    if full_name and full_name.strip():
        return full_name.strip()
    # Fall back to the email local-part with a friendly capitalisation.
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").replace("-", " ").title() or "User"


async def register_individual(
    db: AsyncSession,
    *,
    product_id: UUID,
    email: str,
    password: str,
    full_name: str | None,
) -> tuple[User, Tenant]:
    """B2C signup. Creates a private tenant-of-1 with `type=individual`
    (the user is the sole owner; same primitives as a B2B register).

    Slug is derived as `usr-<8hex>`; one retry on the astronomical
    chance of collision."""
    for _ in range(3):
        slug = _derive_individual_slug()
        try:
            return await register(
                db,
                product_id=product_id,
                tenant_name=_derive_individual_name(email, full_name),
                tenant_slug=slug,
                email=email,
                password=password,
                full_name=full_name,
                tenant_type=TenantType.INDIVIDUAL,
            )
        except Conflict:
            # Slug collision — try again with a fresh one.
            continue
    raise Conflict("could not derive a unique slug after retries (extreme bad luck)")


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
        # Filter out soft-deleted rows: after a user is re-invited under the
        # same email, two rows share (product_id, email) — one with
        # deleted_at SET and is_active=False, one alive. Without this
        # filter, db.scalar's row order is undefined and login can pick
        # the dead row → "invalid credentials" on a correct password.
        stmt = (
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.email == email.lower(),
                User.product_id == product_id,
                User.deleted_at.is_(None),
            )
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
        ttl_seconds=await _refresh_ttl_seconds(db, user.product_id),
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
        ttl_seconds=await _refresh_ttl_seconds(db, user.product_id),
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


# --- forgot / reset password ------------------------------------------------

PASSWORD_RESET_TTL_HOURS = 1


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest. We only persist this — never the raw token."""
    return sha256(raw.encode("utf-8")).hexdigest()


async def request_password_reset(
    db: AsyncSession,
    *,
    product_id: UUID,
    email: str,
    ip_address: str | None = None,
) -> tuple[str | None, datetime | None]:
    """Mint a single-use reset token for the given email in the product.

    Returns (raw_token, expires_at) when a token was issued, or (None, None)
    if the email doesn't match any user — the caller should ALWAYS return
    the same 200 envelope to avoid leaking which emails are registered.

    Until SMTP is wired, the caller may surface the raw token to the
    inviter in non-production environments (see route handler).
    """
    with bypass_product(), bypass_tenant():
        user = await db.scalar(
            select(User).where(
                User.product_id == product_id,
                User.email == email.lower(),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
    if user is None:
        # Don't audit — leaking via audit log would mirror the timing-leak
        # of telling the caller. We log at debug level only.
        log.debug("password_reset.unknown_email", email=email, product_id=str(product_id))
        return None, None

    raw_token = token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=PASSWORD_RESET_TTL_HOURS)
    db.add(PasswordResetToken(
        product_id=product_id,
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=expires_at,
        requested_ip=ip_address,
    ))
    await db.flush()
    await audit.record(
        db, action="user.password_reset_requested", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, product_id=product_id,
        diff={"ip": ip_address},
    )
    return raw_token, expires_at


async def confirm_password_reset(
    db: AsyncSession, *, token: str, new_password: str
) -> User:
    """Validate the token, set the new password, mark token used, and
    revoke every refresh token for the user (force re-login)."""
    token_hash = _hash_token(token)
    now = datetime.now(UTC)
    with bypass_product(), bypass_tenant():
        record = await db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
    if record is None:
        raise NotFound("reset token not found")
    if record.used_at is not None:
        raise Unauthorized("reset token already used")
    if record.expires_at <= now:
        raise Unauthorized("reset token expired")

    with bypass_product(), bypass_tenant():
        user = await db.scalar(select(User).where(User.id == record.user_id))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("user inactive or missing")

    user.password_hash = hash_password(new_password)
    record.used_at = now
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.flush()
    await audit.record(
        db, action="user.password_reset", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, product_id=user.product_id,
    )
    return user


# --- Google OAuth login -----------------------------------------------------

GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


async def login_with_google(
    db: AsyncSession,
    *,
    product_id: UUID,
    code: str,
    redirect_uri: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str, datetime]:
    """OAuth2 authorization-code flow.

    1. Exchange `code` with Google for an access token.
    2. Fetch userinfo → email, name, sub.
    3. Look up existing user in the product by email. If not found AND the
       product opts in via `settings.features.google_auto_provision`,
       auto-create a tenant + user (B2C-style, same shape as
       register_individual). Otherwise 401 — admin must invite first.
    4. Issue platform JWTs as if the user logged in normally.

    Google client_id / client_secret resolution (in order):
      1. ``ProductEnvVar`` rows ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``
         for this product — set via ``PUT /admin/products/{slug}/env/{KEY}``.
      2. Platform-global ``settings.google_client_id`` / ``...secret``
         (env vars on the API process). Back-compat fallback so existing
         deployments keep working until they migrate to per-product vault.

    If neither is set the call 401s with "not configured".
    """
    import httpx

    from app.services import env_var as env_svc

    client_id = await env_svc.get_value_or_default(
        db, product_id=product_id, key="GOOGLE_CLIENT_ID",
        default=settings.google_client_id,
    )
    client_secret = await env_svc.get_value_or_default(
        db, product_id=product_id, key="GOOGLE_CLIENT_SECRET",
        default=settings.google_client_secret,
    )
    if not client_id or not client_secret:
        raise Unauthorized("Google login is not configured on this platform")

    async with httpx.AsyncClient(timeout=10.0) as http:
        token_resp = await http.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uri":  redirect_uri,
            "grant_type":    "authorization_code",
        })
        if token_resp.status_code != 200:
            log.warning("google.token_exchange_failed",
                        status=token_resp.status_code, body=token_resp.text[:300])
            raise Unauthorized("google code exchange failed")
        access = token_resp.json().get("access_token")
        if not access:
            raise Unauthorized("google response missing access_token")

        info_resp = await http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access}"},
        )
        if info_resp.status_code != 200:
            raise Unauthorized("google userinfo failed")
        info = info_resp.json()

    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified", False):
        raise Unauthorized("google account has no verified email")
    full_name = info.get("name")

    with bypass_product(), bypass_tenant():
        user = await db.scalar(
            select(User).where(
                User.product_id == product_id,
                User.email == email,
                User.deleted_at.is_(None),
            )
        )

    if user is None:
        # Auto-provision (B2C-style) if the product opts in. Otherwise the
        # user must be invited via /users first.
        product = await db.get(__import__("app.models.product",
                                          fromlist=["Product"]).Product, product_id)
        features = (product.settings or {}).get("features", {}) if product else {}
        if not features.get("google_auto_provision", False):
            raise Unauthorized("no account for this email; ask an admin to invite you")
        user, _tenant = await register_individual(
            db,
            product_id=product_id,
            email=email,
            password=token_urlsafe(32),  # random — user logs in via Google
            full_name=full_name,
        )

    if not user.is_active:
        raise Unauthorized("user inactive")

    set_current_product(user.product_id)
    set_current_tenant(user.tenant_id)
    user.last_login_at = datetime.now(UTC)
    access_token, _, access_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="access",
    )
    refresh_token, refresh_jti, refresh_exp = issue_token(
        subject=user.id, tenant_id=user.tenant_id,
        product_id=user.product_id, typ="refresh",
        ttl_seconds=await _refresh_ttl_seconds(db, user.product_id),
    )
    db.add(RefreshToken(
        product_id=user.product_id, user_id=user.id, jti=refresh_jti,
        expires_at=refresh_exp, user_agent=user_agent, ip_address=ip_address,
    ))
    await audit.record(
        db, action="user.login_google", actor_user_id=user.id, actor_ip=ip_address,
        resource_type="user", resource_id=user.id,
        tenant_id=user.tenant_id, product_id=user.product_id,
        diff={"google_sub": info.get("sub")},
    )
    return user, access_token, refresh_token, access_exp
