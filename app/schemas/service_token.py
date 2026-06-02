"""Pydantic schemas for per-product service tokens."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Allowed scope strings. Add new entries as new product-scoped endpoints land.
ALLOWED_SCOPES = frozenset({"env:read"})


class ServiceTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name:       str             = Field(min_length=1, max_length=128)
    scopes:     list[str]       = Field(default_factory=lambda: ["env:read"])
    expires_at: datetime | None = None  # None => never expires (rotate via admin)


class ServiceTokenResponse(BaseModel):
    """Metadata-only — used in list / get. Never includes the secret."""

    id:           UUID
    name:         str
    scopes:       list[str]
    expires_at:   datetime | None
    revoked_at:   datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    created_at:   datetime
    updated_at:   datetime


class ServiceTokenIssued(ServiceTokenResponse):
    """Returned ONCE at creation — includes the raw ``pst_…`` token.

    The platform never stores the plaintext; this is the only moment
    you can copy it. After this response, ``token_hash`` (server side)
    is the only record. Lose it = revoke and reissue.
    """

    token: str
