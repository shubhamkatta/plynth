"""Per-product components + per-user enable/disable overrides.

A "component" is a discrete feature module within a product (e.g.
``voice-overlay``, ``morning-brief``, ``news-triage`` for Mayva). The
platform owns the catalog; tenant admins toggle access per-user.

Effective access for (user, component):
1. Look up the override row → ``is_enabled``. If present, that wins.
2. Otherwise fall back to the component's ``is_default_enabled``.

This keeps the default permissive ("user gets every component") and
makes restrictions explicit. Bulk-toggle for a whole product is
achieved by flipping ``is_default_enabled`` on the component itself
(no per-user fan-out needed).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
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


class ProductComponent(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """The catalog. One row per (product_id, code)."""

    __tablename__ = "product_components"
    __table_args__ = (
        UniqueConstraint("product_id", "code", name="uq_product_components_product_code"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # True (default) = all users in the product get access unless an
    # explicit per-user override disables them. False = "opt-in only" —
    # users need an explicit override row to access.
    is_default_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # True = component is live. False = hidden from listings + access
    # checks fail uniformly. Soft kill switch for rollouts.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Free-form per-component config (e.g. feature flags, billing keys,
    # rate limits). Returned verbatim by GET /components.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Plan-driven access gate.
    #
    # - NULL → no plan restriction. Default-permissive: every user gets
    #   the component (modulo overrides).
    # - non-empty list → tenant's active subscription's plan_code must
    #   be one of these to inherit ``is_default_enabled``. Tenants on
    #   any other plan get is_enabled=False (source="plan").
    #
    # Per-user overrides still win, so admins can grandfather a single
    # user or grant beta access without changing their plan.
    required_plan_codes: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, default=None,
    )


class UserComponentOverride(
    UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base
):
    """Per-user override of a component's default. Absent row → default."""

    __tablename__ = "user_component_overrides"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "component_id",
            name="uq_user_component_overrides_user_component",
        ),
        Index("ix_user_component_overrides_user_id", "user_id"),
        Index("ix_user_component_overrides_component_id", "component_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_components.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    set_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
