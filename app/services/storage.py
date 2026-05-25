"""Per-tenant key/value storage service (`docs/architecture.md` § 6.3).

Lifecycle:
1. Caller registers a collection: `create_collection`.
2. Documents land under it: `put_document` (upsert, version-bumping).
3. `get_document` / `list_documents` for reads (incl. `since=` delta sync).
4. `delete_document` for explicit removal.

Every write audits as `storage.<verb>`. Collection and document reads stay
silent — they happen too often to be useful in audit, and they don't change
state. Value size cap (`MAX_VALUE_BYTES`) is enforced at the service level
so a misbehaving client can't fill a tenant's quota with one PUT; a more
nuanced per-product quota will land alongside the `Plan.features`
storage.* keys in a follow-up.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.models.storage import StorageCollection, StorageDocument
from app.services import audit

# Hard cap per value, matching § 6.3 ("≤ 1 MB enforced server-side").
MAX_VALUE_BYTES: int = 1 * 1024 * 1024


def _measure(value: dict) -> int:
    """JSON-encoded byte size of the value. Cheap enough to do per-write."""
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


# ---------- collections ------------------------------------------------------


async def get_collection(
    db: AsyncSession, *, product_id: UUID, tenant_id: UUID, name: str
) -> StorageCollection:
    coll = await db.scalar(
        select(StorageCollection).where(
            StorageCollection.product_id == product_id,
            StorageCollection.tenant_id == tenant_id,
            StorageCollection.name == name,
        )
    )
    if coll is None:
        raise NotFound(f"collection {name!r} not found")
    return coll


async def create_collection(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    name: str,
    description: str | None = None,
    default_ttl_seconds: int = 0,
    actor_user_id: UUID | None = None,
) -> StorageCollection:
    """Idempotent: returns the existing collection if name already taken."""
    existing = await db.scalar(
        select(StorageCollection).where(
            StorageCollection.product_id == product_id,
            StorageCollection.tenant_id == tenant_id,
            StorageCollection.name == name,
        )
    )
    if existing is not None:
        return existing

    coll = StorageCollection(
        product_id=product_id,
        tenant_id=tenant_id,
        name=name,
        description=description,
        default_ttl_seconds=default_ttl_seconds,
    )
    db.add(coll)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent create lost the race — fetch + return the winner.
        await db.rollback()
        return await get_collection(
            db, product_id=product_id, tenant_id=tenant_id, name=name,
        )

    await audit.record(
        db,
        action="storage.collection_create",
        actor_user_id=actor_user_id,
        resource_type="storage_collection",
        resource_id=coll.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"name": name, "default_ttl_seconds": default_ttl_seconds},
    )
    return coll


# ---------- documents --------------------------------------------------------


def _expires_at(ttl_seconds: int | None, collection_default: int) -> datetime | None:
    effective = ttl_seconds if ttl_seconds is not None else collection_default
    if effective is None or effective <= 0:
        return None
    return datetime.now(UTC) + timedelta(seconds=effective)


async def _get_document_row(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    collection_id: UUID,
    key: str,
) -> StorageDocument | None:
    return await db.scalar(
        select(StorageDocument).where(
            StorageDocument.product_id == product_id,
            StorageDocument.tenant_id == tenant_id,
            StorageDocument.collection_id == collection_id,
            StorageDocument.key == key,
        )
    )


async def put_document(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    collection_name: str,
    key: str,
    value: dict,
    ttl_seconds: int | None = None,
    if_version: int | None = None,
    actor_user_id: UUID | None = None,
) -> StorageDocument:
    """Upsert. Bumps `version` by 1 on each write. Honours `if_version` for
    optimistic concurrency — mismatch raises `Conflict`."""
    if not key:
        raise ValidationFailed("key is required")
    if _measure(value) > MAX_VALUE_BYTES:
        raise ValidationFailed(
            f"value exceeds {MAX_VALUE_BYTES} bytes",
            details={"max_bytes": MAX_VALUE_BYTES},
        )

    coll = await get_collection(
        db, product_id=product_id, tenant_id=tenant_id, name=collection_name,
    )
    doc = await _get_document_row(
        db,
        product_id=product_id,
        tenant_id=tenant_id,
        collection_id=coll.id,
        key=key,
    )
    if doc is None:
        if if_version is not None:
            raise Conflict(
                "if_version supplied on first write",
                details={"key": key, "current_version": 0},
            )
        doc = StorageDocument(
            product_id=product_id,
            tenant_id=tenant_id,
            collection_id=coll.id,
            key=key,
            value=value,
            version=1,
            expires_at=_expires_at(ttl_seconds, coll.default_ttl_seconds),
        )
        db.add(doc)
        action = "storage.put"
    else:
        if if_version is not None and doc.version != if_version:
            raise Conflict(
                f"version mismatch: have {doc.version}, expected {if_version}",
                details={
                    "key": key,
                    "current_version": doc.version,
                    "if_version": if_version,
                },
            )
        doc.value = value
        doc.version = doc.version + 1
        doc.expires_at = _expires_at(ttl_seconds, coll.default_ttl_seconds)
        action = "storage.update"

    await db.flush()
    await audit.record(
        db,
        action=action,
        actor_user_id=actor_user_id,
        resource_type="storage_document",
        resource_id=doc.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"collection": collection_name, "key": key, "version": doc.version},
    )
    return doc


async def get_document(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    collection_name: str,
    key: str,
) -> StorageDocument:
    """Read. Treats expired rows as missing — clients see 404, the row
    is left in place for the background sweeper to reap."""
    coll = await get_collection(
        db, product_id=product_id, tenant_id=tenant_id, name=collection_name,
    )
    doc = await _get_document_row(
        db,
        product_id=product_id,
        tenant_id=tenant_id,
        collection_id=coll.id,
        key=key,
    )
    if doc is None:
        raise NotFound(f"key {key!r} not found in {collection_name!r}")
    if doc.expires_at is not None and doc.expires_at <= datetime.now(UTC):
        raise NotFound(f"key {key!r} expired")
    return doc


async def list_documents(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    collection_name: str,
    since: datetime | None = None,
    prefix: str | None = None,
    limit: int = 100,
) -> Sequence[StorageDocument]:
    """List for delta sync (`since=<iso-ts>`) and / or key-prefix scan.
    Cursoring is not yet wired — `limit` clamps the page size."""
    coll = await get_collection(
        db, product_id=product_id, tenant_id=tenant_id, name=collection_name,
    )
    stmt = (
        select(StorageDocument)
        .where(
            StorageDocument.product_id == product_id,
            StorageDocument.tenant_id == tenant_id,
            StorageDocument.collection_id == coll.id,
        )
        .order_by(StorageDocument.updated_at.asc())
        .limit(max(1, min(limit, 500)))
    )
    if since is not None:
        stmt = stmt.where(StorageDocument.updated_at > since)
    if prefix:
        stmt = stmt.where(StorageDocument.key.like(f"{prefix}%"))
    return (await db.scalars(stmt)).all()


async def delete_document(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    collection_name: str,
    key: str,
    actor_user_id: UUID | None = None,
) -> None:
    """Idempotent — deleting an absent key is a no-op (returns silently
    so the route can still respond 204)."""
    coll = await get_collection(
        db, product_id=product_id, tenant_id=tenant_id, name=collection_name,
    )
    doc = await _get_document_row(
        db,
        product_id=product_id,
        tenant_id=tenant_id,
        collection_id=coll.id,
        key=key,
    )
    if doc is None:
        return
    await db.delete(doc)
    await db.flush()
    await audit.record(
        db,
        action="storage.delete",
        actor_user_id=actor_user_id,
        resource_type="storage_document",
        resource_id=doc.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"collection": collection_name, "key": key},
    )
