"""Billing-provider webhooks.

Always verify the signature (provider parses+verifies in `parse_webhook`).
We respond 200 quickly to keep the provider happy; expensive side-effects
should be off-loaded to arq jobs.

No `X-Product-Slug` header is required — product is derived from the
subscription the event refers to (which is looked up via
`provider_subscription_id`).

Error handling rules:
- Signature failure → log warning, return 400. NEVER 500 — providers will
  retry indefinitely and we'll flood the logs.
- Unknown event type → log info, return 200 (provider can add new types).
- Persisted side-effects → wrapped in audit.record so we can reconstruct.
"""

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import bypass_product, bypass_tenant, set_current_product
from app.models.invoice import InvoiceStatus
from app.models.subscription import Subscription
from app.providers.billing import get_billing_provider
from app.services import audit, billing as billing_svc

router = APIRouter()
log = structlog.get_logger("webhook")


@router.post("/billing", status_code=status.HTTP_200_OK)
async def billing_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> JSONResponse:
    body = await request.body()
    provider = get_billing_provider()

    try:
        event = await provider.parse_webhook(payload=body, signature=stripe_signature or "")
    except Exception as exc:
        log.warning(
            "webhook.signature_invalid", provider=provider.name,
            error=str(exc), has_signature=bool(stripe_signature),
        )
        return JSONResponse(
            {"code": "invalid_signature", "message": "Webhook signature invalid", "details": {}},
            status_code=400,
        )

    log.info("webhook.received", provider=provider.name, event_id=event.id, type=event.type)

    with bypass_product(), bypass_tenant():
        if event.type in ("invoice.payment_succeeded", "invoice.paid"):
            data = event.data
            sub = await db.scalar(
                select(Subscription).where(
                    Subscription.provider_subscription_id == data.get("subscription")
                )
            )
            if sub is None:
                log.warning("webhook.subscription_missing", event_id=event.id,
                            provider_sub=data.get("subscription"))
                return JSONResponse({"received": "true"}, status_code=200)
            set_current_product(sub.product_id)
            inv = await billing_svc.record_invoice(
                db,
                product_id=sub.product_id, tenant_id=sub.tenant_id,
                subscription_id=sub.id,
                provider=provider.name, provider_invoice_id=data["id"],
                amount_cents=data.get("amount_paid", 0),
                currency=data.get("currency", "USD").upper(),
                status=InvoiceStatus.PAID,
                issued_at=datetime.fromtimestamp(data.get("created", 0), tz=UTC),
                due_at=datetime.fromtimestamp(data.get("due_date", data.get("created", 0)), tz=UTC),
            )
            await billing_svc.handle_payment_succeeded(db, invoice_id=inv.id)
            await audit.record(
                db, action="webhook.payment_succeeded",
                resource_type="invoice", resource_id=inv.id,
                tenant_id=sub.tenant_id, product_id=sub.product_id,
                diff={"event_id": event.id, "provider": provider.name},
            )

        elif event.type == "invoice.payment_failed":
            data = event.data
            sub = await db.scalar(
                select(Subscription).where(
                    Subscription.provider_subscription_id == data.get("subscription")
                )
            )
            if sub is None:
                log.warning("webhook.subscription_missing", event_id=event.id,
                            provider_sub=data.get("subscription"))
                return JSONResponse({"received": "true"}, status_code=200)
            set_current_product(sub.product_id)
            inv = await billing_svc.record_invoice(
                db,
                product_id=sub.product_id, tenant_id=sub.tenant_id,
                subscription_id=sub.id,
                provider=provider.name, provider_invoice_id=data["id"],
                amount_cents=data.get("amount_due", 0),
                currency=data.get("currency", "USD").upper(),
                status=InvoiceStatus.OPEN,
                issued_at=datetime.fromtimestamp(data.get("created", 0), tz=UTC),
                due_at=datetime.fromtimestamp(data.get("due_date", data.get("created", 0)), tz=UTC),
            )
            await billing_svc.handle_payment_failed(db, invoice_id=inv.id)
            await audit.record(
                db, action="webhook.payment_failed",
                resource_type="invoice", resource_id=inv.id,
                tenant_id=sub.tenant_id, product_id=sub.product_id,
                diff={"event_id": event.id, "provider": provider.name,
                      "attempt": inv.attempt_count},
            )
        else:
            log.info("webhook.ignored", event_id=event.id, type=event.type)

    return JSONResponse({"received": "true"}, status_code=200)
