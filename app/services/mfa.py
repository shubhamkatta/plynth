"""MFA enrollment, challenge, and verification.

Supports two methods:
- ``totp`` — TOTP authenticator app (Google Authenticator, Authy, etc.)
- ``email`` — 6-digit OTP sent to the user's verified email address.
"""

import hmac
import secrets
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pyotp
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, RateLimited, Unauthorized, ValidationFailed
from app.core.redis import get_redis
from app.core.security import decode_token, issue_token
from app.core.tenant import bypass_product, bypass_tenant
from app.models.user import User
from app.providers import notifications
from app.schemas.auth import MfaChallengeRequired
from app.services import audit
from app.services import auth as auth_svc

log = structlog.get_logger("mfa")

MFA_OTP_KEY = "mfa:otp:{user_id}"
MFA_OTP_TTL = 300
MFA_OTP_COOLDOWN = 60


async def setup_totp(db: AsyncSession, *, user: User) -> tuple[str, str]:
    """Generate a TOTP secret for the user. Returns (secret, provisioning_uri).
    MFA is NOT enabled until ``confirm_setup`` is called."""
    if user.mfa_method:
        raise Conflict("MFA is already enabled; disable it first")

    secret = pyotp.random_base32()
    user.mfa_secret = secret
    await db.flush()

    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Plynth")

    await audit.record(
        db, action="user.mfa_totp_setup", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
    )
    return secret, uri


async def setup_email(db: AsyncSession, *, user: User) -> None:
    """Send a verification OTP to the user's email.
    MFA is NOT enabled until ``confirm_setup`` is called."""
    if user.mfa_method:
        raise Conflict("MFA is already enabled; disable it first")
    await _send_otp(user)
    await audit.record(
        db, action="user.mfa_email_setup", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
    )


async def confirm_setup(
    db: AsyncSession, *, user: User, method: str, code: str,
) -> None:
    """Verify a setup code and enable MFA."""
    if user.mfa_method:
        raise Conflict("MFA is already enabled")

    if method == "totp":
        if not user.mfa_secret:
            raise ValidationFailed("call POST /auth/mfa/totp/setup first")
        _verify_totp_code(user, code)
    elif method == "email":
        await _verify_otp(user, code)
    else:
        raise ValidationFailed(f"unsupported MFA method: {method}")

    user.mfa_method = method
    user.mfa_enabled_at = datetime.now(UTC)
    await db.flush()

    await audit.record(
        db, action="user.mfa_enabled", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
        diff={"method": method},
    )
    log.info("mfa.enabled", user_id=str(user.id), method=method)


async def create_challenge(
    db: AsyncSession, *, user: User,
) -> MfaChallengeRequired:
    """Issue a short-lived MFA challenge token. For email method, sends OTP."""
    if not user.mfa_method:
        raise ValidationFailed("MFA is not enabled")

    if user.mfa_method == "email":
        await _send_otp(user)

    token, _, exp = issue_token(
        subject=user.id,
        tenant_id=user.tenant_id,
        product_id=user.product_id,
        typ="mfa",
        extra={"mfa": user.mfa_method},
    )
    return MfaChallengeRequired(
        mfa_method=user.mfa_method,
        mfa_token=token,
        mfa_token_expires_at=exp,
    )


async def verify_challenge(
    db: AsyncSession,
    *,
    mfa_token: str,
    code: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str, datetime]:
    """Verify an MFA code and complete the login flow."""
    import jwt

    try:
        payload = decode_token(mfa_token, expected_type="mfa")
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"invalid MFA token: {exc}") from exc

    user_id = UUID(payload["sub"])
    with bypass_product(), bypass_tenant():
        user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("user inactive or missing")
    if not user.mfa_method:
        raise Unauthorized("MFA is no longer enabled")

    try:
        if user.mfa_method == "totp":
            _verify_totp_code(user, code)
        elif user.mfa_method == "email":
            await _verify_otp(user, code)
        else:
            raise Unauthorized("unknown MFA method")
    except Unauthorized:
        log.warning(
            "mfa.verify_failed", user_id=str(user_id),
            method=user.mfa_method, ip=ip_address,
        )
        await _audit_mfa_failed(user, ip_address)
        raise

    return await auth_svc.complete_login(
        db, user=user, user_agent=user_agent, ip_address=ip_address,
        audit_diff={"mfa_method": user.mfa_method},
    )


async def disable_mfa(
    db: AsyncSession, *, user: User, code: str,
) -> None:
    """Verify the current MFA code and disable MFA."""
    if not user.mfa_method:
        raise ValidationFailed("MFA is not enabled")

    if user.mfa_method == "totp":
        _verify_totp_code(user, code)
    elif user.mfa_method == "email":
        await _verify_otp(user, code)

    old_method = user.mfa_method
    user.mfa_method = None
    user.mfa_secret = None
    user.mfa_enabled_at = None
    await db.flush()

    await audit.record(
        db, action="user.mfa_disabled", actor_user_id=user.id,
        resource_type="user", resource_id=user.id,
        diff={"method": old_method},
    )
    log.info("mfa.disabled", user_id=str(user.id), method=old_method)


# --- internal helpers -------------------------------------------------------

def _verify_totp_code(user: User, code: str) -> None:
    if not user.mfa_secret:
        raise Unauthorized("TOTP not configured")
    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        raise Unauthorized("invalid TOTP code")


async def _send_otp(user: User) -> None:
    redis = get_redis()
    key = MFA_OTP_KEY.format(user_id=user.id)

    ttl = await redis.ttl(key)
    if ttl > MFA_OTP_TTL - MFA_OTP_COOLDOWN:
        raise RateLimited("please wait before requesting another code")

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = sha256(code.encode()).hexdigest()
    await redis.set(key, code_hash, ex=MFA_OTP_TTL)

    await notifications.send_email(
        to=user.email,
        template="mfa_otp",
        context={"code": code, "expires_minutes": MFA_OTP_TTL // 60},
    )


async def _verify_otp(user: User, code: str) -> None:
    redis = get_redis()
    key = MFA_OTP_KEY.format(user_id=user.id)
    stored_hash = await redis.get(key)
    if not stored_hash:
        raise Unauthorized("verification code expired or not sent")

    code_hash = sha256(code.encode()).hexdigest()
    stored_str = stored_hash.decode() if isinstance(stored_hash, bytes) else stored_hash
    if not hmac.compare_digest(code_hash, stored_str):
        raise Unauthorized("invalid verification code")

    await redis.delete(key)


async def _audit_mfa_failed(user: User, ip_address: str | None) -> None:
    from app.core.database import session_scope

    async with session_scope() as tx:
        await audit.record(
            tx, action="user.mfa_verify_failed", actor_user_id=user.id,
            actor_ip=ip_address, resource_type="user", resource_id=user.id,
            tenant_id=user.tenant_id, product_id=user.product_id,
        )
