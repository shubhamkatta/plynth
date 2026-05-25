"""Outbound webhook lifecycle + dispatch.

Responsibilities:

- CRUD on `WebhookEndpoint` rows (per product, admin-managed).
- Generate signing secrets on create.
- Match a fired event type against an endpoint's event filter (glob).
- Sign payloads (Stripe-style HMAC-SHA256).
- `dispatch()` — given (product_id, event_type, payload), fan out a
  pending `WebhookDelivery` row per matching endpoint. The actual HTTP
  POST runs in the arq worker — that wiring is a separate concern
  (the worker reads `pending` rows, signs, posts, updates the row).

Tenant scoping: webhook endpoints are PRODUCT-scoped, not tenant-scoped
— they describe an integration owned by the product itself. We don't
write audit rows here using the request's tenant context because the
admin caller is operating against the product's root tenant; the route
layer passes `tenant_id` explicitly via the `audit.record` helper so
the audit is correctly attributed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.webhook_endpoint import WebhookDelivery, WebhookEndpoint

log = structlog.get_logger("webhook.outbound")

# Truncate persisted response bodies; remote servers can be arbitrarily verbose.
_MAX_RESPONSE_BODY_BYTES = 4 * 1024


# -- secret generation + signing ---------------------------------------------

def _generate_secret() -> str:
    """64-char URL-safe token. `secrets.token_urlsafe(32)` returns ~43 chars;
    we pad to a fixed width with another nibble of entropy to fit the column
    while keeping things human-copyable."""
    return secrets.token_urlsafe(32)[:64]


def sign_payload(*, secret: str, body: str, timestamp: int | None = None) -> str:
    """Build the `X-Plynth-Signature` header value for `body`.

    Format: `t=<unix_ts>,v1=<hex>` where hex is HMAC-SHA256(secret, "{ts}.{body}").
    Subscribers MUST verify the timestamp is recent (e.g. < 5 min) before
    trusting the signature — protects against replay if the body is logged
    somewhere downstream.
    """
    ts = int(time.time()) if timestamp is None else int(timestamp)
    msg = f"{ts}.{body}".encode()
    digest = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


# -- event-type matching ------------------------------------------------------

def _event_matches(filter_pattern: str, event_type: str) -> bool:
    """Glob match `subscription.*` against `subscription.purchase`.

    Rules:
    - exact equality always matches;
    - `*` matches any single trailing segment after a dot;
    - `*` alone matches any event.
    """
    if filter_pattern == "*" or filter_pattern == event_type:
        return True
    if filter_pattern.endswith(".*"):
        prefix = filter_pattern[:-2]
        return event_type == prefix or event_type.startswith(prefix + ".")
    return False


def endpoint_accepts(endpoint: WebhookEndpoint, event_type: str) -> bool:
    """Empty filter list = subscribe to everything."""
    if not endpoint.events:
        return True
    return any(_event_matches(f, event_type) for f in endpoint.events)


# -- CRUD ---------------------------------------------------------------------

async def create(
    db: AsyncSession,
    *,
    product_id: UUID,
    url: str,
    description: str | None,
    events: list[str],
) -> tuple[WebhookEndpoint, str]:
    """Register a new endpoint. Returns (row, plaintext_secret).

    The secret is intentionally returned separately even though it's
    also stored on the row — keeps the caller honest about which path
    surfaces it (the create response, exactly once).
    """
    secret = _generate_secret()
    endpoint = WebhookEndpoint(
        product_id=product_id,
        url=url,
        description=description,
        secret=secret,
        events=list(events),
        is_active=True,
    )
    # The repository layer is tenant-scoped; webhook endpoints are
    # product-scoped only. Bypass tenant filtering for the flush.
    with bypass_tenant():
        db.add(endpoint)
        await db.flush()
    return endpoint, secret


async def list_for_product(
    db: AsyncSession, *, product_id: UUID
) -> list[WebhookEndpoint]:
    with bypass_product(), bypass_tenant():
        result = await db.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.product_id == product_id)
            .order_by(WebhookEndpoint.created_at.desc())
        )
        return list(result.all())


async def get_or_404(
    db: AsyncSession, *, product_id: UUID, endpoint_id: UUID
) -> WebhookEndpoint:
    """Fetch an endpoint; 404 if it doesn't exist OR belongs to another product.

    The product check is the per-product isolation gate — we never let an
    admin operating on /admin/products/foo/webhooks see endpoints owned
    by product bar even if they guess the UUID.
    """
    with bypass_product(), bypass_tenant():
        endpoint = await db.scalar(
            select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id)
        )
    if endpoint is None or endpoint.product_id != product_id:
        raise NotFound(f"webhook endpoint {endpoint_id} not found")
    return endpoint


async def update(
    db: AsyncSession,
    *,
    product_id: UUID,
    endpoint_id: UUID,
    fields: dict[str, Any],
) -> WebhookEndpoint:
    endpoint = await get_or_404(db, product_id=product_id, endpoint_id=endpoint_id)
    for key in ("url", "description", "events", "is_active"):
        if key in fields and fields[key] is not None:
            setattr(endpoint, key, fields[key])
    with bypass_tenant():
        await db.flush()
    return endpoint


async def set_active(
    db: AsyncSession,
    *,
    product_id: UUID,
    endpoint_id: UUID,
    is_active: bool,
) -> WebhookEndpoint:
    endpoint = await get_or_404(db, product_id=product_id, endpoint_id=endpoint_id)
    endpoint.is_active = is_active
    with bypass_tenant():
        await db.flush()
    return endpoint


async def delete(
    db: AsyncSession, *, product_id: UUID, endpoint_id: UUID
) -> WebhookEndpoint:
    """Soft-deactivate. Hard-delete would cascade away the delivery
    history, which is exactly what an admin debugging a flaky integration
    does NOT want."""
    return await set_active(
        db, product_id=product_id, endpoint_id=endpoint_id, is_active=False
    )


# -- recent deliveries dashboard ---------------------------------------------

async def recent_deliveries(
    db: AsyncSession,
    *,
    product_id: UUID,
    endpoint_id: UUID,
    limit: int = 50,
) -> list[WebhookDelivery]:
    # Make sure the endpoint belongs to this product before exposing
    # delivery rows.
    await get_or_404(db, product_id=product_id, endpoint_id=endpoint_id)
    with bypass_product(), bypass_tenant():
        result = await db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.endpoint_id == endpoint_id)
            .order_by(desc(WebhookDelivery.created_at))
            .limit(max(1, min(limit, 500)))
        )
        return list(result.all())


# -- dispatch (fan-out) -------------------------------------------------------

async def dispatch(
    db: AsyncSession,
    *,
    product_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    request_id: str | None = None,
) -> list[WebhookDelivery]:
    """Fan out one event to every active, matching endpoint in this product.

    Persists `WebhookDelivery` rows in `pending` status. The actual HTTP
    POST is left to the worker (see TODO below). Returns the rows created
    — useful for tests and for the synchronous `/test` route.

    TODO(worker): enqueue an arq job per delivery to run
    `_perform_delivery(delivery_id)` which fetches the row, signs with
    `sign_payload(secret=endpoint.secret, body=json_body)`, POSTs, then
    updates `status`, `response_status`, `response_body`, `delivered_at`,
    `attempt`, `next_retry_at` (exponential backoff).
    """
    endpoints = await list_for_product(db, product_id=product_id)
    matched = [
        ep for ep in endpoints if ep.is_active and endpoint_accepts(ep, event_type)
    ]
    if not matched:
        log.info(
            "webhook.dispatch.no_match",
            product_id=str(product_id), event_type=event_type,
        )
        return []

    created: list[WebhookDelivery] = []
    with bypass_product(), bypass_tenant():
        for ep in matched:
            delivery = WebhookDelivery(
                endpoint_id=ep.id,
                product_id=product_id,
                event_type=event_type,
                payload=payload,
                request_id=request_id,
                attempt=0,
                status="pending",
            )
            db.add(delivery)
            created.append(delivery)
        await db.flush()

    log.info(
        "webhook.dispatch.queued",
        product_id=str(product_id), event_type=event_type,
        endpoint_count=len(matched),
    )
    return created


# -- response-body persistence helper (for the worker) -----------------------

def truncate_response_body(body: str | bytes | None) -> str | None:
    """Helpers shared with the (not-yet-implemented) worker — keep the
    truncation policy in one place so an admin reading the dashboard
    never sees a multi-megabyte error page."""
    if body is None:
        return None
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", errors="replace")
        except Exception:
            body = body.decode("latin-1", errors="replace")
    if len(body.encode("utf-8")) <= _MAX_RESPONSE_BODY_BYTES:
        return body
    # Slice on character boundary, then re-check bytes.
    truncated = body[:_MAX_RESPONSE_BODY_BYTES]
    while len(truncated.encode("utf-8")) > _MAX_RESPONSE_BODY_BYTES:
        truncated = truncated[:-1]
    return truncated + "...[truncated]"


def serialize_payload(payload: dict[str, Any]) -> str:
    """Canonical JSON serialization used for both POST body and HMAC input.
    Sort keys so subscribers can re-derive the signature without
    Python-specific ordering assumptions."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
