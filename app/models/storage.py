"""Per-tenant key/value storage (`docs/architecture.md` § 6.3).

The Electron UI needs to round-trip per-user state (recent files, project
state, preferences) across devices without operating its own backend. We
offer a thin JSON kv store under `(product, tenant, collection, key)` —
collections are an explicit registration step so quotas and TTL defaults
can be enforced per collection (vs. an open free-for-all namespace).

Two tables:
- `storage_collections` — registry of named buckets per (product, tenant).
  Validation rules and default TTL live here.
- `storage_documents` — the actual kv rows, dual-scoped by (product,
  tenant) and additionally keyed by `collection_id` so a delete of the
  collection cascades.

Blob uploads (§ 6.3.1 `storage_blob_uploads`) are intentionally deferred
to a follow-up: the JSON kv store is the only piece needed to ship the
Electron sync feature today.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    ProductScopedMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)


class StorageCollection(
    UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base
):
    """A named bucket within (product, tenant). Created on demand by the
    `POST /storage/collections` endpoint; documents live below."""

    __tablename__ = "storage_collections"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "tenant_id", "name",
            name="uq_storage_collections_name",
        ),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Per-collection ttl in seconds applied at PUT time when the caller
    # doesn't specify one. `0` means "no expiry by default".
    default_ttl_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class StorageDocument(
    UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base
):
    """A single (collection, key) → JSON document. `version` is bumped on
    every PUT to support optimistic concurrency (`If-Match: W/"<version>"`
    is part of the contract but enforced at the service layer)."""

    __tablename__ = "storage_documents"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "tenant_id", "collection_id", "key",
            name="uq_storage_documents_key",
        ),
        # Delta-sync queries hit this index hard: scan a collection by
        # last-updated for incremental pull.
        Index(
            "ix_storage_documents_sync",
            "product_id", "tenant_id", "collection_id", "updated_at",
        ),
    )

    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("storage_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
