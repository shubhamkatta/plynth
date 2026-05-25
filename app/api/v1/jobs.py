"""HTTP surface for the Jobs API (`docs/architecture.md` § 6.2).

Routes are thin adapters: schema in → service call → schema out. Every
mutating route is RBAC-gated; reads use `jobs:read`. The `POST /jobs`
endpoint honours `Idempotency-Key` so retried client requests return the
original job rather than enqueuing a duplicate.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    CurrentUser,
    actor_id,
    get_idempotency_key,
    require_permission,
)
from app.core.tenant import acting_from_tenant_id, current_tenant_id
from app.models.job import Job, JobStatus
from app.schemas.job import (
    JobAcceptedResponse,
    JobCreateRequest,
    JobListResponse,
    JobResponse,
)
from app.services import job as job_svc

router = APIRouter()


def _serialise(job: Job) -> JobResponse:
    """Map the ORM row → wire shape. We hand-roll because the column is
    `id` but the spec'd wire field is `job_id`."""
    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        payload=job.payload or {},
        result=job.result,
        error=job.error,
        reference=job.reference,
        credits_charged=job.credits_charged,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
    )


@router.post(
    "",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("jobs:write"))],
)
async def create_job(
    payload: JobCreateRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
) -> JobAcceptedResponse:
    tid = current_tenant_id() or user.tenant_id
    job = await job_svc.enqueue(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        type_=payload.type,
        payload=payload.payload,
        callback_url=str(payload.callback_url) if payload.callback_url else None,
        reference=payload.reference,
        ttl_seconds=payload.ttl_seconds,
        idempotency_key=idempotency_key,
        actor_user_id=actor_id(user),
        acting_from_tenant_id=acting_from_tenant_id(),
    )
    return JobAcceptedResponse(
        job_id=job.id, status=job.status, poll_url=f"/api/v1/jobs/{job.id}"
    )


@router.get(
    "",
    response_model=JobListResponse,
    dependencies=[Depends(require_permission("jobs:read"))],
)
async def list_jobs(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[JobStatus | None, Query()] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    reference: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JobListResponse:
    """Lists current tenant's jobs, newest first. `status` is a query
    param (`?status=queued`) — FastAPI auto-validates the enum value."""
    tid = current_tenant_id() or user.tenant_id
    jobs = await job_svc.list_jobs(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        status=status,
        type_=type,
        reference=reference,
        limit=limit,
    )
    return JobListResponse(items=[_serialise(j) for j in jobs])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    dependencies=[Depends(require_permission("jobs:read"))],
)
async def get_job(
    job_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobResponse:
    tid = current_tenant_id() or user.tenant_id
    job = await job_svc.get(
        db, product_id=user.product_id, tenant_id=tid, job_id=job_id
    )
    return _serialise(job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    dependencies=[Depends(require_permission("jobs:cancel"))],
)
async def cancel_job(
    job_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobResponse:
    """Only `queued` jobs can be cancelled (service raises 409 otherwise)."""
    tid = current_tenant_id() or user.tenant_id
    job = await job_svc.cancel(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        job_id=job_id,
        actor_user_id=actor_id(user),
    )
    return _serialise(job)
