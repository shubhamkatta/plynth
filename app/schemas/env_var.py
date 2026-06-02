"""Pydantic schemas for the per-product env-vars vault."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,127}$"


class EnvVarSet(BaseModel):
    """PUT body — create-or-update a single env var.

    ``key`` is in the URL; only the value + flags live here. Setting a
    value always re-encrypts (or re-stores) and stamps ``last_rotated_at``.
    """

    model_config = ConfigDict(extra="forbid")

    value:       str          = Field(min_length=1, max_length=16384)
    is_secret:   bool         = True
    description: str | None   = Field(default=None, max_length=255)


class EnvVarPatch(BaseModel):
    """PATCH body — adjust metadata without rotating the value.

    ``value`` is intentionally not patchable here; rotate via PUT so the
    audit trail always reflects an explicit rotation.
    """

    model_config = ConfigDict(extra="forbid")

    is_secret:   bool | None = None
    description: str | None  = Field(default=None, max_length=255)


class EnvVarListItem(BaseModel):
    """List response — never includes the plaintext value. Secret values
    show a masked ``preview`` (first/last 4 chars only); public values
    show their full plaintext in ``value``."""

    key:             str
    is_secret:       bool
    description:     str | None
    last_rotated_at: datetime
    preview:         str | None = None  # set for is_secret=true only
    value:           str | None = None  # set for is_secret=false only


class EnvVarDetail(BaseModel):
    """Reveal response — admin GET with ?reveal=true. Audited
    high-severity. Returns the plaintext value verbatim."""

    key:             str
    value:           str
    is_secret:       bool
    description:     str | None
    last_rotated_at: datetime
    created_at:      datetime
    updated_at:      datetime
