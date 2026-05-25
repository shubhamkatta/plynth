"""Admin routes for OUTBOUND webhooks.

Mounted at `/admin/products/{slug}/webhooks`. All routes require a valid
`X-Platform-Admin-Token` (no per-user RBAC yet — see permission codes at
the bottom of `app/services/webhook_endpoint.py` for the future
per-tenant self-service surface).

This module is intentionally separate from `app/api/v1/webhooks.py`,
which handles INCOMING billing webhooks. Don't conflate the two —
incoming = "Stripe POSTs us", outgoing = "we POST our customers".

Audit:
- create / update / delete / test all write an `audit.record` entry.
- The signing secret is NEVER included in the audit diff (or in any
  response after the one-shot create).

Tenancy:
- Webhook endpoints are PRODUCT-scoped, not tenant-scoped. We resolve
  the product from the path slug and set the product context so audit
  writes attribute correctly to the product's root tenant.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_platform_admin
from app.core.exceptions import NotFound
from app.core.tenant import (
    bypass_product,
    bypass_tenant,
    set_current_product,
    set_current_tenant,
)
from app.models.tenant import Tenant
from app.schemas.webhook_endpoint import (
    WebhookDeliveryResponse,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointResponse,
    WebhookEndpointUpdate,
)
from app.services import audit
from app.services import product as product_svc
from app.services import webhook_endpoint as webhook_svc

router = APIRouter(dependencies=[Depends(require_platform_admin)])


async def _resolve_product_slug(db: AsyncSession, slug: str) -> UUID:
    """Resolve `{slug}` from the path to a product_id.

    Also wires up the request-level product + tenant context so that
    `audit.record(...)` can attribute the action to the product's root
    tenant. (Admin webhook calls don't carry `X-Product-Slug` because
    the slug is in the URL; without this priming, audit would skip.)
    """
    with bypass_product(), bypass_tenant():
        product = await product_svc.get_by_slug(db, slug)
    if product is None:
        raise NotFound(f"product {slug!r} not found")
    set_current_product(product.id)
    # Best-effort root-tenant lookup for audit attribution. If the product
    # has no tenants yet, the audit call will simply skip (see audit.py).
    with bypass_product(), bypass_tenant():
        root = await db.scalar(
            select(Tenant)
            .where(
                Tenant.product_id == product.id,
                Tenant.parent_id.is_(None),
                Tenant.deleted_at.is_(None),
            )
            .order_by(Tenant.created_at)
            .limit(1)
        )
    if root is not None:
        set_current_tenant(root.id)
    return product.id


@router.post(
    "",
    response_model=WebhookEndpointCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Register a webhook endpoint (secret returned once)",
)
async def create_webhook(
    slug: Annotated[str, Path()],
    payload: WebhookEndpointCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookEndpointCreated:
    product_id = await _resolve_product_slug(db, slug)
    endpoint, secret = await webhook_svc.create(
        db,
        product_id=product_id,
        url=payload.url,
        description=payload.description,
        events=payload.events,
    )
    await audit.record(
        db,
        action="webhook.create",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        product_id=product_id,
        diff={
            "url": endpoint.url,
            "events": endpoint.events,
            "description": endpoint.description,
            # Intentionally NOT including `secret` — never write it to audit.
        },
    )
    # Build the create response with the plaintext secret. Subsequent
    # GETs use the slimmer `WebhookEndpointResponse` schema that omits it.
    base = WebhookEndpointResponse.model_validate(endpoint).model_dump()
    return WebhookEndpointCreated(**base, secret=secret)


@router.get(
    "",
    response_model=list[WebhookEndpointResponse],
    summary="List webhook endpoints for this product",
)
async def list_webhooks(
    slug: Annotated[str, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    product_id = await _resolve_product_slug(db, slug)
    return await webhook_svc.list_for_product(db, product_id=product_id)


@router.get(
    "/{endpoint_id}",
    response_model=WebhookEndpointResponse,
    summary="Show one webhook endpoint",
)
async def get_webhook(
    slug: Annotated[str, Path()],
    endpoint_id: Annotated[UUID, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    product_id = await _resolve_product_slug(db, slug)
    return await webhook_svc.get_or_404(
        db, product_id=product_id, endpoint_id=endpoint_id
    )


@router.patch(
    "/{endpoint_id}",
    response_model=WebhookEndpointResponse,
    summary="Update a webhook endpoint",
)
async def update_webhook(
    slug: Annotated[str, Path()],
    endpoint_id: Annotated[UUID, Path()],
    payload: WebhookEndpointUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    product_id = await _resolve_product_slug(db, slug)
    changes = payload.model_dump(exclude_unset=True)
    endpoint = await webhook_svc.update(
        db, product_id=product_id, endpoint_id=endpoint_id, fields=changes,
    )
    await audit.record(
        db,
        action="webhook.update",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        product_id=product_id,
        diff={k: v for k, v in changes.items() if k != "secret"},
    )
    return endpoint


@router.delete(
    "/{endpoint_id}",
    response_model=WebhookEndpointResponse,
    summary="Soft-deactivate a webhook endpoint (preserves delivery history)",
)
async def delete_webhook(
    slug: Annotated[str, Path()],
    endpoint_id: Annotated[UUID, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    product_id = await _resolve_product_slug(db, slug)
    endpoint = await webhook_svc.delete(
        db, product_id=product_id, endpoint_id=endpoint_id,
    )
    await audit.record(
        db,
        action="webhook.delete",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        product_id=product_id,
        diff={"is_active": False},
    )
    return endpoint


@router.get(
    "/{endpoint_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
    summary="Recent delivery attempts for an endpoint",
)
async def list_deliveries(
    slug: Annotated[str, Path()],
    endpoint_id: Annotated[UUID, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list:
    product_id = await _resolve_product_slug(db, slug)
    return await webhook_svc.recent_deliveries(
        db, product_id=product_id, endpoint_id=endpoint_id, limit=limit,
    )


@router.post(
    "/{endpoint_id}/test",
    response_model=WebhookDeliveryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a synthetic webhook.test event NOW (for setup verification)",
)
async def test_webhook(
    slug: Annotated[str, Path()],
    endpoint_id: Annotated[UUID, Path()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    product_id = await _resolve_product_slug(db, slug)
    # Confirms the endpoint exists in this product (404 otherwise).
    endpoint = await webhook_svc.get_or_404(
        db, product_id=product_id, endpoint_id=endpoint_id,
    )
    payload = {
        "event": "webhook.test",
        "endpoint_id": str(endpoint.id),
        "message": "If you can read this, your endpoint is wired up.",
    }
    # `dispatch` will return only matching endpoints. `webhook.test` is a
    # synthetic event; if the admin set a strict `events` filter that
    # doesn't allow it, we still want the test to land — so write the
    # delivery row directly rather than going through the filter.
    from app.models.webhook_endpoint import WebhookDelivery
    with bypass_product(), bypass_tenant():
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            product_id=product_id,
            event_type="webhook.test",
            payload=payload,
            attempt=0,
            status="pending",
        )
        db.add(delivery)
        await db.flush()
    await audit.record(
        db,
        action="webhook.test_dispatched",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        product_id=product_id,
        diff={"delivery_id": str(delivery.id)},
    )
    return delivery
