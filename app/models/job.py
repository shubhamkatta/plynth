"""Background-job persistence layer.

The Jobs API (`docs/architecture.md` § 6.2) lets clients (typically the
Electron desktop) enqueue long-running work — transcription, ML inference,
bulk import, project-wide sync — and poll for status. The platform stores
the row here; an `arq` worker can later pick unhandled rows up and dispatch
by `type`. This module owns the storage shape only; dispatch is out of
scope until handler registry lands.

Every job is dual-scoped via `(product_id, tenant_id)` so the
`TenantRepository` automatically isolates reads and writes; cross-tenant
or cross-product access requires explicit `bypass_*()` (none for Jobs).
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
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


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# State transitions a job can legally take. Terminal states (done / failed /
# cancelled) are absorbing — once reached the row never changes status again.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}
)


class Job(UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base):
    """A single enqueued unit of work. See `app/services/job.py` for the API."""

    __tablename__ = "jobs"
    __table_args__ = (
        # `(product_id, tenant_id, status)` is the dominant filter for list
        # endpoints; the partial unique on idempotency key lets retries
        # find the original row (NULL keys are not unique, naturally).
        Index("ix_jobs_product_tenant_status", "product_id", "tenant_id", "status"),
        Index(
            "uq_jobs_idempotency",
            "product_id", "tenant_id", "type", "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )

    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        default=JobStatus.QUEUED,
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Structured `{ "code": str, "message": str }` — keep it small.
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Client-correlation id (any opaque string) — separate from idempotency.
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    credits_charged: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Mirrors `audit_log.acting_from_tenant_id` — the user's home tenant when
    # the job was enqueued from a parent-acting-as-child request.
    acting_from_tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
