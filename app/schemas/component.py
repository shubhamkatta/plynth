"""Pydantic schemas for per-product components + per-user overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Conventional component code: lowercase, kebab-case. Same shape as a
# URL slug so it composes cleanly into paths.
_CODE_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"


class ComponentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    is_default_enabled: bool = True
    is_active: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class ComponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    is_default_enabled: bool | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None


class ComponentResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_default_enabled: bool
    is_active: bool
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UserComponentOverrideSet(BaseModel):
    """PUT body — set an override for a user. Pass is_enabled=true to
    grant a component to a user where it would otherwise be off (because
    its default is false). Pass is_enabled=false to revoke it from a
    user where it would otherwise be on."""

    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    reason: str | None = Field(default=None, max_length=255)


class UserComponentStatus(BaseModel):
    """One row in the user's effective component map."""

    code: str
    name: str
    is_enabled: bool
    # "default" = inherits is_default_enabled
    # "override" = explicit per-user override row
    source: str
    description: str | None = None
    reason: str | None = None  # set only when source="override"
