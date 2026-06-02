"""Per-product service tokens — issue, authenticate, revoke.

A token is one row in ``product_service_tokens``. The wire format is
``pst_<32-hex>`` (44 chars total). We persist only the SHA-256 hex of
the bearer; a DB leak cannot recover the plaintext.

Authentication path (called from the ``RequireServiceToken`` dependency):

    raw token → hash → row lookup → liveness + scope check → row
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.tenant import bypass_product, bypass_tenant
from app.models.service_token import ProductServiceToken
from app.schemas.service_token import ALLOWED_SCOPES
from app.services import audit

TOKEN_PREFIX = "pst_"
TOKEN_BYTES  = 16  # 16 bytes → 32 hex chars; 128 bits entropy


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_hex(TOKEN_BYTES)}"


def _validate_scopes(scopes: list[str]) -> None:
    bad = set(scopes) - ALLOWED_SCOPES
    if bad:
        raise ValidationFailed(
            f"unknown scopes: {sorted(bad)}",
            details={"allowed": sorted(ALLOWED_SCOPES)},
        )


async def issue(
    db: AsyncSession,
    *,
    product_id: UUID,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
    actor_user_id: UUID | None = None,
) -> tuple[ProductServiceToken, str]:
    """Mint a fresh service token. Returns (row, raw_token).

    The raw token is the ONLY moment the plaintext exists outside the
    caller's request. Surface it in the API response and forget it.
    """
    _validate_scopes(scopes)
    raw = _generate_token()
    row = ProductServiceToken(
        product_id=product_id,
        name=name,
        token_hash=_hash_token(raw),
        scopes=scopes,
        expires_at=expires_at,
    )
    with bypass_product(), bypass_tenant():
        db.add(row)
        await db.flush()
        await audit.record(
            db,
            action="service_token.issued",
            actor_user_id=actor_user_id,
            resource_type="service_token",
            resource_id=row.id,
            product_id=product_id,
            diff={"name": name, "scopes": scopes, "expires_at": (
                expires_at.isoformat() if expires_at else None
            )},
        )
    return row, raw


async def list_for_product(
    db: AsyncSession, *, product_id: UUID
) -> list[ProductServiceToken]:
    with bypass_product(), bypass_tenant():
        rows = (
            await db.scalars(
                select(ProductServiceToken)
                .where(ProductServiceToken.product_id == product_id)
                .order_by(ProductServiceToken.created_at.desc())
            )
        ).all()
    return list(rows)


async def revoke(
    db: AsyncSession,
    *,
    product_id: UUID,
    token_id: UUID,
    actor_user_id: UUID | None = None,
) -> ProductServiceToken:
    with bypass_product(), bypass_tenant():
        row = await db.scalar(
            select(ProductServiceToken).where(
                ProductServiceToken.id == token_id,
                ProductServiceToken.product_id == product_id,
            )
        )
        if row is None:
            raise NotFound("service token not found")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await db.flush()
            await audit.record(
                db,
                action="service_token.revoked",
                actor_user_id=actor_user_id,
                resource_type="service_token",
                resource_id=row.id,
                product_id=product_id,
                diff={"name": row.name},
            )
    return row


async def authenticate(
    db: AsyncSession,
    *,
    raw: str,
    required_scope: str,
    client_ip: str | None = None,
) -> ProductServiceToken:
    """Resolve a raw bearer to a live token row, asserting ``required_scope``.

    Raises ``Unauthorized`` on every failure path that's input-shape /
    secret material (no auth row, hash miss, revoked, expired). Raises
    ``Forbidden`` only when the token IS valid but lacks the scope —
    that distinction matters for the operator (revoke vs widen scopes).

    Updates ``last_used_at`` + ``last_used_ip`` on the matched row.
    """
    if not raw or not raw.startswith(TOKEN_PREFIX):
        raise Unauthorized("missing or malformed service token")
    digest = _hash_token(raw)
    with bypass_product(), bypass_tenant():
        row = await db.scalar(
            select(ProductServiceToken).where(
                ProductServiceToken.token_hash == digest,
            )
        )
        if row is None:
            raise Unauthorized("invalid service token")
        now = datetime.now(UTC)
        if row.revoked_at is not None:
            raise Unauthorized("service token revoked")
        if row.expires_at is not None and row.expires_at <= now:
            raise Unauthorized("service token expired")
        if required_scope not in (row.scopes or []):
            raise Forbidden(f"service token missing required scope: {required_scope}")
        row.last_used_at = now
        if client_ip:
            row.last_used_ip = client_ip[:64]
        await db.flush()
    return row
