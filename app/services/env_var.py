"""Per-product env-vars vault — CRUD with at-rest encryption + audit.

The single source of truth for reading/writing rows in
``product_env_vars``. Routes never touch the model directly; they go
through ``set_var``, ``get_var``, ``list_vars``, ``delete_var``.

Encryption is applied / unwound here so callers see plaintext strings.
Every state-changing operation writes an audit row. Reveals are
high-severity and carry the operator-supplied reason in ``diff.reason``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import aad_for, decrypt, encrypt, mask_preview
from app.core.exceptions import NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.env_var import ProductEnvVar
from app.services import audit

# Keys matching these patterns remain in the vault — admin can read /
# rotate / reveal them — but are filtered out of the product-runtime
# ``GET /api/v1/env`` response. They're "server-only" credentials that
# the platform uses on the product's behalf without ever returning to
# the client. Today: Google OAuth client secrets used by the
# ``/integrations/google/exchange`` endpoint (see ARCHITECTURE.md § 6.6).
#
# Extend this list as more platform-mediated integrations land. Operators
# get visibility via ``is_server_only`` in the admin list response.
SERVER_ONLY_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^GOOGLE_(.*_)?CLIENT_SECRET$"),
)


def is_server_only(key: str) -> bool:
    """True if ``key`` should be hidden from the product-runtime /env
    response (still admin-readable)."""
    return any(p.match(key) for p in SERVER_ONLY_KEY_PATTERNS)


async def set_var(
    db: AsyncSession,
    *,
    product_id: UUID,
    key: str,
    value: str,
    is_secret: bool = True,
    description: str | None = None,
    actor_user_id: UUID | None = None,
) -> ProductEnvVar:
    """Create or update a single env var. Idempotent on (product_id, key).

    Always stamps ``last_rotated_at`` so the audit story for "when did
    this credential last change?" is direct. The plaintext is never
    persisted to the audit diff — only the metadata.
    """
    aad = aad_for(product_id=str(product_id), key=key)
    stored = encrypt(value, aad=aad) if is_secret else value.encode("utf-8")
    now = datetime.now(UTC)

    with bypass_product(), bypass_tenant():
        row = await db.scalar(
            select(ProductEnvVar).where(
                ProductEnvVar.product_id == product_id,
                ProductEnvVar.key == key,
            )
        )
        action = "env.var_rotated" if row else "env.var_created"
        if row is None:
            row = ProductEnvVar(
                product_id=product_id,
                key=key,
                value_encrypted=stored,
                is_secret=is_secret,
                description=description,
                last_rotated_at=now,
            )
            db.add(row)
        else:
            row.value_encrypted = stored
            row.is_secret = is_secret
            if description is not None:
                row.description = description
            row.last_rotated_at = now
        await db.flush()
        await audit.record(
            db,
            action=action,
            actor_user_id=actor_user_id,
            resource_type="env_var",
            resource_id=row.id,
            product_id=product_id,
            # Plaintext never goes to audit — only metadata. The fact
            # that the value changed is enough for forensics.
            diff={"key": key, "is_secret": is_secret, "value_present": True},
        )
    return row


async def list_vars(
    db: AsyncSession, *, product_id: UUID
) -> list[ProductEnvVar]:
    """All env-vars for a product. Plaintext not unwrapped — caller
    decides whether to mask, reveal, or skip the value per row."""
    with bypass_product(), bypass_tenant():
        rows = (
            await db.scalars(
                select(ProductEnvVar)
                .where(ProductEnvVar.product_id == product_id)
                .order_by(ProductEnvVar.key)
            )
        ).all()
    return list(rows)


async def get_var(
    db: AsyncSession, *, product_id: UUID, key: str
) -> ProductEnvVar:
    with bypass_product(), bypass_tenant():
        row = await db.scalar(
            select(ProductEnvVar).where(
                ProductEnvVar.product_id == product_id,
                ProductEnvVar.key == key,
            )
        )
    if row is None:
        raise NotFound(f"env var {key!r} not found in product")
    return row


def reveal(row: ProductEnvVar) -> str:
    """Decrypt the stored value. For is_secret=false rows the bytes are
    utf-8 plaintext — decoded directly without touching the cipher."""
    if not row.is_secret:
        return row.value_encrypted.decode("utf-8")
    aad = aad_for(product_id=str(row.product_id), key=row.key)
    return decrypt(row.value_encrypted, aad=aad)


def preview(row: ProductEnvVar) -> str | None:
    """A short, safe preview for list responses on secrets. Returns
    ``None`` for non-secret rows (caller renders the plaintext instead)."""
    if not row.is_secret:
        return None
    try:
        return mask_preview(reveal(row))
    except Exception:
        # Decryption failed (likely key rotation pending). Don't leak
        # the ciphertext — just say so.
        return "<decryption-failed>"


async def delete_var(
    db: AsyncSession, *, product_id: UUID, key: str, actor_user_id: UUID | None = None
) -> None:
    row = await get_var(db, product_id=product_id, key=key)
    with bypass_product(), bypass_tenant():
        await db.delete(row)
        await audit.record(
            db,
            action="env.var_deleted",
            actor_user_id=actor_user_id,
            resource_type="env_var",
            resource_id=row.id,
            product_id=product_id,
            diff={"key": key},
        )


async def record_reveal(
    db: AsyncSession,
    *,
    product_id: UUID,
    key: str,
    actor_user_id: UUID | None,
    reason: str,
    ip_address: str | None = None,
) -> None:
    """Write the high-severity audit row that admin reveals trigger.

    Separate from the service operation so the route can also reject
    early if reason is empty — the audit only fires once we know we'll
    actually hand back the plaintext.
    """
    with bypass_product(), bypass_tenant():
        await audit.record(
            db,
            action="env.var_revealed",
            actor_user_id=actor_user_id,
            actor_ip=ip_address,
            resource_type="env_var",
            product_id=product_id,
            diff={"key": key, "reason": reason},
        )


# ---------------------------------------------------------------------
# Convenience: fetch a single value, falling back to platform settings.
# Used by app.services.auth for the Google OAuth credentials migration.
# ---------------------------------------------------------------------

async def get_value_or_default(
    db: AsyncSession,
    *,
    product_id: UUID,
    key: str,
    default: str,
) -> str:
    """Return the decrypted value for ``(product_id, key)`` if it exists,
    otherwise ``default``.

    Lets callers migrate from a platform-global env-var to a per-product
    one without breaking back-compat. Pass the existing setting as
    ``default`` and the new path takes over once the admin writes a
    per-product value.
    """
    try:
        row = await get_var(db, product_id=product_id, key=key)
    except NotFound:
        return default
    return reveal(row)
