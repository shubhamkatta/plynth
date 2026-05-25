"""Pydantic shapes for the Storage API (`docs/architecture.md` § 6.3)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class StorageCollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    description: str | None = Field(default=None, max_length=255)
    # 0 means "no default expiry" — explicit per-key ttl_seconds still wins.
    default_ttl_seconds: int = Field(default=0, ge=0, le=60 * 60 * 24 * 365)


class StorageCollectionResponse(ORMModel):
    id: UUID
    name: str
    description: str | None
    default_ttl_seconds: int
    created_at: datetime
    updated_at: datetime


class StoragePutRequest(BaseModel):
    """`PUT /storage/{collection}/{key}` body. `value` must be a JSON object
    (top-level scalar/list values are rejected — keep the shape predictable
    for delta-sync diffing)."""
    value: dict[str, Any] = Field(default_factory=dict)
    # `null` → "use the collection default"; explicit `0` → "never expire".
    ttl_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 24 * 365)
    # Optimistic concurrency: caller asserts they last saw this version.
    # Mismatch → 409.
    if_version: int | None = Field(default=None, ge=1)


class StorageValueResponse(BaseModel):
    """`GET` and `PUT` both respond with this shape so the client can chain
    write → cache without a second round-trip."""
    key: str
    value: dict[str, Any]
    version: int
    expires_at: datetime | None
    updated_at: datetime


class StorageDocumentListItem(BaseModel):
    """`GET /storage/{collection}` returns these — value omitted to keep
    list responses cheap for delta-sync sweeps."""
    key: str
    version: int
    updated_at: datetime
    expires_at: datetime | None


class StorageListResponse(BaseModel):
    items: list[StorageDocumentListItem]
    next_cursor: str | None = None
