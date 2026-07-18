"""Pydantic schemas for per-product components + per-user overrides."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Conventional component code: lowercase, starts with a letter, then
# letters / digits / hyphen / underscore. Composes cleanly into paths and
# matches the code style used by plan codes and credit feature_keys
# (both of which already permit underscores, e.g. `credits.ai_completion`).
_CODE_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class ComponentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    is_default_enabled: bool = True
    is_active: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    # Plan-driven gate. `null` (default) = no plan restriction. A list
    # means "only tenants on one of these plan codes inherit
    # is_default_enabled". Empty list is treated as null for safety —
    # use `is_active=false` to fully disable.
    required_plan_codes: list[str] | None = Field(default=None, max_length=64)


class ComponentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)
    is_default_enabled: bool | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None
    # Pass an empty list (or omit) to leave unchanged; pass `null`
    # explicitly to clear the restriction.
    required_plan_codes: list[str] | None = Field(default=None, max_length=64)


class ComponentResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_default_enabled: bool
    is_active: bool
    settings: dict[str, Any]
    required_plan_codes: list[str] | None
    created_at: datetime
    updated_at: datetime


class UserComponentOverrideSet(BaseModel):
    """PUT body — set an override for a user. Pass is_enabled=true to
    grant a component to a user where it would otherwise be off (because
    its default is false or the user's plan doesn't include it). Pass
    is_enabled=false to revoke it from a user where it would otherwise
    be on."""

    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    reason: str | None = Field(default=None, max_length=255)


class UserComponentStatus(BaseModel):
    """One row in the user's effective component map."""

    code: str
    name: str
    is_enabled: bool
    # "default"         = inherits is_default_enabled (no plan gate, or gate satisfied)
    # "plan"            = plan-gated and user's plan doesn't qualify → False
    # "tenant_override" = a per-tenant override row decided
    # "override"        = a per-user override row decided (highest precedence)
    source: str
    description: str | None = None
    reason: str | None = None  # set when source ∈ {"override", "tenant_override"}
    # Set when source="plan" — the codes the user would need to be on.
    required_plan_codes: list[str] | None = None


class TenantComponentOverrideSet(BaseModel):
    """PUT body — set a per-tenant override. Applies to every user in
    the tenant unless overridden by a per-user override."""

    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    reason: str | None = Field(default=None, max_length=255)


class TenantComponentStatus(BaseModel):
    """Tenant-level effective row — ignores per-user overrides."""

    code: str
    name: str
    is_enabled: bool
    # "default"         = no override, no plan gate (or gate satisfied)
    # "plan"            = plan-gated and not qualifying
    # "tenant_override" = explicit per-tenant row decided
    source: str
    description: str | None = None
    reason: str | None = None  # set when source="tenant_override"
    required_plan_codes: list[str] | None = None  # set when source="plan"
