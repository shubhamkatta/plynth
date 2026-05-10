"""Password hashing + JWT issuance/verification.

Argon2id is the OWASP-recommended password hash. JWT is used for stateless
access tokens; refresh tokens are also JWT but with a separate `typ` claim and
should additionally be tracked server-side (see `app/services/auth.py`) so they
can be revoked on logout/password-change.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()  # default params are OWASP-recommended

TokenType = Literal["access", "refresh"]


# --- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# --- jwt ---------------------------------------------------------------------

def _ttl(typ: TokenType) -> int:
    return (
        settings.jwt_access_ttl_seconds
        if typ == "access"
        else settings.jwt_refresh_ttl_seconds
    )


def issue_token(
    *,
    subject: UUID | str,
    tenant_id: UUID | str | None,
    product_id: UUID | str | None,
    typ: TokenType = "access",
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Return `(jwt_string, jti, expires_at)`. Encodes:
    `sub` (user), `tid` (tenant), `pid` (product), `typ`, `iat`, `exp`, `jti`.
    """
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=_ttl(typ))
    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tid": str(tenant_id) if tenant_id else None,
        "pid": str(product_id) if product_id else None,
        "typ": typ,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, exp


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if expected_type is not None and payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"expected token type {expected_type}, got {payload.get('typ')}")
    return payload
