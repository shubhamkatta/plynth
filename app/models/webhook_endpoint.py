"""Outbound webhook endpoints + their delivery log.

A `WebhookEndpoint` is a URL registered by a platform admin against a
single product. When something interesting happens inside that product
(subscription transition, tenant lifecycle event, credit grant, audit
event), the platform POSTs a signed JSON body to every registered URL
whose `events` filter matches.

`WebhookDelivery` is the append-only attempt log — one row per (endpoint,
event) attempt. The actual HTTP POST runs in an arq worker; the request
handler only persists the `pending` row and enqueues the job.

Signing scheme (Stripe-style):

    X-Plynth-Signature: t=<unix_ts>,v1=<hex_hmac_sha256(secret, "{ts}.{body}")>

The `secret` is auto-generated on create with `secrets.token_urlsafe(32)`
and is returned **once** to the admin in the create response. It is
stored in plaintext (not hashed) because we need it on every dispatch to
re-derive the HMAC. Soft-deactivate (`is_active=false`) rather than
hard-delete so the delivery history stays referenceable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, ProductScopedMixin, TimestampMixin, UUIDPKMixin


class WebhookEndpoint(UUIDPKMixin, TimestampMixin, ProductScopedMixin, Base):
    """A subscriber URL inside one product."""

    __tablename__ = "webhook_endpoints"

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Stored in plaintext — required to re-derive the HMAC on each dispatch.
    # Never returned by list / get endpoints; the create response returns it
    # once and only once.
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # Whitelist of event types. Wildcards allowed (`subscription.*`).
    # Empty list = "all events".
    events: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WebhookDelivery(UUIDPKMixin, TimestampMixin, Base):
    """One attempt at delivering one event to one endpoint."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # Recent-deliveries dashboard scans per-product, newest first.
        Index(
            "ix_webhook_deliveries_product_created",
            "product_id",
            "created_at",
        ),
        Index("ix_webhook_deliveries_endpoint_id", "endpoint_id"),
    )

    endpoint_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized for the dashboard query (recent deliveries for product X)
    # without joining through the endpoint table.
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # pending | success | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Truncated server-side to 4 KB before write — service layer enforces.
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
