"""Job lifecycle: enqueue → run → terminal (done | failed | cancelled).

Designed in `docs/architecture.md` § 6.2. This module owns persistence and
state transitions only; the actual dispatch (arq handlers, the registry,
the optional SSE stream) lands in `app/jobs/` later. Until then the rows
live in `jobs` and a worker is free to pick them up and call `mark_done`
/ `mark_failed` from the side.

Idempotency: `POST /jobs` may pass `idempotency_key`. The partial unique
index on `(product_id, tenant_id, type, idempotency_key)` enforces that
the second call with the same key returns the first job rather than
creating a new row. We catch the IntegrityError and re-fetch — racey
clients converge.

Audit: every state change (`job.create`, `job.cancel`, `job.complete`,
`job.fail`) writes an audit entry via `audit.record`. Terminal-state
side-effects (callback POST etc.) are out of scope for the storage layer
and will be triggered by the worker.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.models.job import TERMINAL_STATUSES, Job, JobStatus
from app.services import audit

# Per-product TTL cap. Clients may request a shorter ttl_seconds; longer
# requests are clamped down silently (callers can read `expires_at` back
# from the response to confirm).
DEFAULT_TTL_SECONDS: int = 60 * 60 * 24
MAX_TTL_SECONDS: int = 60 * 60 * 24 * 7


def _clamp_ttl(requested: int | None) -> int:
    if requested is None:
        return DEFAULT_TTL_SECONDS
    return max(1, min(requested, MAX_TTL_SECONDS))


async def _find_by_idempotency_key(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    type_: str,
    idempotency_key: str,
) -> Job | None:
    return await db.scalar(
        select(Job).where(
            Job.product_id == product_id,
            Job.tenant_id == tenant_id,
            Job.type == type_,
            Job.idempotency_key == idempotency_key,
        )
    )


async def enqueue(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    type_: str,
    payload: dict,
    callback_url: str | None = None,
    reference: str | None = None,
    ttl_seconds: int | None = None,
    idempotency_key: str | None = None,
    actor_user_id: UUID | None = None,
    acting_from_tenant_id: UUID | None = None,
) -> Job:
    """Create a queued Job row. Returns the existing row on idempotent replay.

    Race-safe: if two requests with the same idempotency key land in
    parallel, the second one trips the partial-unique index and we re-fetch
    the row that won.
    """
    if not type_:
        raise ValidationFailed("type is required")

    if idempotency_key is not None:
        existing = await _find_by_idempotency_key(
            db,
            product_id=product_id,
            tenant_id=tenant_id,
            type_=type_,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing

    now = datetime.now(UTC)
    job = Job(
        product_id=product_id,
        tenant_id=tenant_id,
        type=type_,
        status=JobStatus.QUEUED,
        payload=payload or {},
        progress=0,
        reference=reference,
        callback_url=callback_url,
        idempotency_key=idempotency_key,
        queued_at=now,
        expires_at=now + timedelta(seconds=_clamp_ttl(ttl_seconds)),
        created_by_user_id=actor_user_id,
        acting_from_tenant_id=acting_from_tenant_id,
    )
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent inserter with the same idempotency_key won. Roll back
        # the partial state and return the row that landed first.
        await db.rollback()
        if idempotency_key is None:
            raise
        existing = await _find_by_idempotency_key(
            db,
            product_id=product_id,
            tenant_id=tenant_id,
            type_=type_,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            # Truly unexpected — re-raise so the global handler maps it.
            raise
        return existing

    await audit.record(
        db,
        action="job.create",
        actor_user_id=actor_user_id,
        resource_type="job",
        resource_id=job.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"type": type_, "reference": reference},
    )
    return job


async def get(
    db: AsyncSession, *, product_id: UUID, tenant_id: UUID, job_id: UUID
) -> Job:
    """Fetch a job by id, enforcing tenant + product isolation."""
    job = await db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.product_id == product_id,
            Job.tenant_id == tenant_id,
        )
    )
    if job is None:
        raise NotFound(f"job {job_id} not found")
    return job


async def list_jobs(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    status: JobStatus | None = None,
    type_: str | None = None,
    reference: str | None = None,
    limit: int = 50,
) -> Sequence[Job]:
    stmt = (
        select(Job)
        .where(Job.product_id == product_id, Job.tenant_id == tenant_id)
        .order_by(Job.queued_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if status is not None:
        stmt = stmt.where(Job.status == status)
    if type_:
        stmt = stmt.where(Job.type == type_)
    if reference:
        stmt = stmt.where(Job.reference == reference)
    return (await db.scalars(stmt)).all()


async def cancel(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    job_id: UUID,
    actor_user_id: UUID | None = None,
) -> Job:
    """Only `queued` jobs can be cancelled. Running / terminal → 409.

    A queued → cancelled transition is itself terminal — once cancelled
    no further state changes are permitted.
    """
    job = await get(db, product_id=product_id, tenant_id=tenant_id, job_id=job_id)
    if job.status != JobStatus.QUEUED:
        raise Conflict(
            f"cannot cancel job in status {job.status.value!r}",
            details={"job_id": str(job.id), "status": job.status.value},
        )
    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        action="job.cancel",
        actor_user_id=actor_user_id,
        resource_type="job",
        resource_id=job.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"type": job.type},
    )
    return job


async def mark_running(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    job_id: UUID,
) -> Job:
    """Worker-side: flip `queued` → `running`. Idempotent on repeat."""
    job = await get(db, product_id=product_id, tenant_id=tenant_id, job_id=job_id)
    if job.status == JobStatus.RUNNING:
        return job
    if job.status != JobStatus.QUEUED:
        raise Conflict(
            f"cannot start job in status {job.status.value!r}",
            details={"job_id": str(job.id), "status": job.status.value},
        )
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await db.flush()
    return job


async def mark_done(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    job_id: UUID,
    result: dict | None = None,
    actor_user_id: UUID | None = None,
) -> Job:
    job = await get(db, product_id=product_id, tenant_id=tenant_id, job_id=job_id)
    if job.status in TERMINAL_STATUSES:
        raise Conflict(
            f"job already terminal ({job.status.value})",
            details={"job_id": str(job.id), "status": job.status.value},
        )
    job.status = JobStatus.DONE
    job.result = result or {}
    job.progress = 100
    job.completed_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        action="job.complete",
        actor_user_id=actor_user_id,
        resource_type="job",
        resource_id=job.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"type": job.type},
    )
    return job


async def mark_failed(
    db: AsyncSession,
    *,
    product_id: UUID,
    tenant_id: UUID,
    job_id: UUID,
    error_code: str,
    error_message: str,
    actor_user_id: UUID | None = None,
) -> Job:
    job = await get(db, product_id=product_id, tenant_id=tenant_id, job_id=job_id)
    if job.status in TERMINAL_STATUSES:
        raise Conflict(
            f"job already terminal ({job.status.value})",
            details={"job_id": str(job.id), "status": job.status.value},
        )
    job.status = JobStatus.FAILED
    job.error = {"code": error_code, "message": error_message}
    job.completed_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        action="job.fail",
        actor_user_id=actor_user_id,
        resource_type="job",
        resource_id=job.id,
        product_id=product_id,
        tenant_id=tenant_id,
        diff={"type": job.type, "error_code": error_code},
    )
    return job
