"""Pydantic shapes for the Jobs API (`docs/architecture.md` § 6.2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models.job import JobStatus


class JobCreateRequest(BaseModel):
    """`POST /jobs` body. Type is a dotted handler code that the worker
    registry dispatches on (e.g. `transcription.audio_to_text`)."""

    type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Stringify so we don't import the urllib HttpUrl validator into model
    # objects — schema validates on the way IN, ORM stores the string.
    callback_url: HttpUrl | None = None
    reference: str | None = Field(default=None, max_length=128)
    # Capped server-side against product limits (currently a hard 7-day
    # ceiling — see service.DEFAULT_TTL_SECONDS).
    ttl_seconds: int | None = Field(default=None, ge=1, le=60 * 60 * 24 * 30)


class JobErrorPayload(BaseModel):
    """Shape for `Job.error` so handlers can't smuggle arbitrary keys back."""
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(max_length=1024)
    model_config = ConfigDict(extra="forbid")


class JobResponse(BaseModel):
    """`§ 6.2.3` — single source of truth for the wire shape.

    Hand-built rather than ORM-derived because the wire field is `job_id`
    while the ORM column is `id`; the route layer maps via `from_orm()`.
    """

    model_config = ConfigDict(from_attributes=False)

    job_id: UUID
    type: str
    status: JobStatus
    progress: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    reference: str | None
    credits_charged: Decimal | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime


class JobAcceptedResponse(BaseModel):
    """`POST /jobs` returns 202 with this thin envelope; the full
    `JobResponse` is available via `poll_url`."""
    job_id: UUID
    status: JobStatus
    poll_url: str


class JobListResponse(BaseModel):
    items: list[JobResponse]
    next_cursor: str | None = None


class JobCompleteRequest(BaseModel):
    """Used by worker callbacks (`POST /jobs/{id}/complete`). Not currently
    exposed on the public router — kept here so the same shape is shared
    once we expose a worker-side completion endpoint."""
    result: dict[str, Any] = Field(default_factory=dict)


class JobFailRequest(BaseModel):
    error: JobErrorPayload
