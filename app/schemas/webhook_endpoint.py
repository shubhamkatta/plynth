"""Request / response shapes for the admin webhook endpoints.

Two key invariants:

1.  The `secret` field is only ever populated on `WebhookEndpointCreated`
    (the response to POST /). List / get / patch responses omit it
    entirely so a stolen DB-dump screenshot doesn't leak signing keys.
2.  URLs are HTTPS-only and capped at 2048 chars. We validate on the
    schema so the service layer can trust its input.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, TimestampedResponse

# Reasonable upper bound on the number of event filters per endpoint —
# unbounded JSONB arrays are a footgun.
MAX_EVENTS_PER_ENDPOINT = 64
EVENT_TYPE_MAX_LEN = 64


def _validate_url(value: str) -> str:
    if not value:
        raise ValueError("url is required")
    if len(value) > 2048:
        raise ValueError("url is too long (max 2048 chars)")
    if not value.lower().startswith("https://"):
        raise ValueError("webhook url must use https://")
    return value


def _validate_events(value: list[str]) -> list[str]:
    if len(value) > MAX_EVENTS_PER_ENDPOINT:
        raise ValueError(
            f"too many event filters (max {MAX_EVENTS_PER_ENDPOINT})"
        )
    cleaned: list[str] = []
    for ev in value:
        if not isinstance(ev, str):
            raise ValueError("event types must be strings")
        ev = ev.strip()
        if not ev:
            raise ValueError("event types may not be empty")
        if len(ev) > EVENT_TYPE_MAX_LEN:
            raise ValueError(
                f"event type {ev!r} too long (max {EVENT_TYPE_MAX_LEN} chars)"
            )
        cleaned.append(ev)
    return cleaned


class WebhookEndpointCreate(BaseModel):
    url: str = Field(..., description="HTTPS endpoint URL")
    description: str | None = Field(default=None, max_length=255)
    events: list[str] = Field(
        default_factory=list,
        description="Whitelist of event types (e.g. 'subscription.*'). "
                    "Empty list = subscribe to all events.",
    )

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_url(v)

    @field_validator("events")
    @classmethod
    def _check_events(cls, v: list[str]) -> list[str]:
        return _validate_events(v)


class WebhookEndpointUpdate(BaseModel):
    url: str | None = None
    description: str | None = Field(default=None, max_length=255)
    events: list[str] | None = None
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return None if v is None else _validate_url(v)

    @field_validator("events")
    @classmethod
    def _check_events(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _validate_events(v)


class WebhookEndpointResponse(TimestampedResponse):
    """List / get response. Never includes the secret."""

    product_id: UUID
    url: str
    description: str | None
    events: list[str]
    is_active: bool


class WebhookEndpointCreated(WebhookEndpointResponse):
    """The one-shot create response that includes the signing secret.

    The admin is expected to copy this immediately — there is no other
    way to recover it. Rotating means deleting the endpoint and
    creating a fresh one.
    """

    secret: str


class WebhookDeliveryResponse(ORMModel):
    id: UUID
    endpoint_id: UUID
    product_id: UUID
    event_type: str
    payload: dict[str, Any]
    request_id: str | None
    attempt: int
    status: str
    response_status: int | None
    response_body: str | None
    delivered_at: datetime | None
    next_retry_at: datetime | None
    created_at: datetime
    updated_at: datetime
