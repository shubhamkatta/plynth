"""Billing-provider webhooks.

Always verify the signature (provider parses+verifies in `parse_webhook`).
We respond 200 quickly to keep the provider happy; expensive side-effects
should be off-loaded to arq jobs.

No `X-Product-Slug` header is required — product is derived from the
subscription the event refers to (which is looked up via
`provider_subscription_id`).

Event names are the **provider's own**, not normalised: `parse_webhook`
returns `body["event"]` for Razorpay and `event["type"]` for Stripe. So the
`invoice.*` branches below are Stripe/mock dialect and the `subscription.*`
ones are Razorpay dialect, and both have to live here. Razorpay has no
`invoice.payment_failed` at all — it expresses the same state as
`subscription.pending` → `subscription.halted`.

Error handling rules:
- Signature failure → log warning, return 400. NEVER 500 — providers will
  retry indefinitely and we'll flood the logs.
- Unknown event type → log info, return 200 (provider can add new types).
- Persisted side-effects → wrapped in audit.record so we can reconstruct.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

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
from app.services import audit
from app.services import billing as billing_svc

router = APIRouter()
log = structlog.get_logger("webhook")

# Razorpay subscription lifecycle events that flip a subscription to ACTIVE.
# `activated` = subscription live, `charged` = a cycle was successfully billed.
# `subscription.authenticated` (mandate authorized, fires DURING the trial before
# any money moves) is deliberately excluded: on a card-on-file trial it would
# flip the status label TRIAL → ACTIVE before the first charge. It is recorded
# as `meta.mandate_authorized_at` instead (see _SUBSCRIPTION_LIFECYCLE_HANDLERS).
_SUBSCRIPTION_ACTIVE_EVENTS = frozenset(
    {"subscription.activated", "subscription.charged"}
)


# Razorpay lifecycle events beyond activation. `payment.failed` is deliberately
# NOT mapped: it carries no subscription id, and `subscription.pending` /
# `.halted` already express the retry / exhausted states.
_SUBSCRIPTION_LIFECYCLE_HANDLERS = {
    "subscription.authenticated": billing_svc.handle_mandate_authorized,
    "subscription.pending": billing_svc.handle_subscription_pending,
    "subscription.halted": billing_svc.handle_subscription_halted,
    "subscription.cancelled": billing_svc.handle_subscription_cancelled,
}


def _extract_provider_subscription_id(data: dict[str, Any]) -> str | None:
    """Pull the provider subscription id out of a webhook payload across the
    two shapes we see: Razorpay nests the entity
    (``{"subscription": {"entity": {"id": ...}}}``) while Stripe-style/invoice
    events carry it as a flat string (``{"subscription": "sub_..."}``)."""
    sub = data.get("subscription")
    if isinstance(sub, dict):
        entity = sub.get("entity") or {}
        return entity.get("id")
    if isinstance(sub, str):
        return sub
    return data.get("subscription_id") or data.get("id")


@router.post("/billing", status_code=status.HTTP_200_OK)
async def billing_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
    razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
) -> JSONResponse:
    body = await request.body()
    provider = get_billing_provider()
    # Stripe signs with `Stripe-Signature`, Razorpay with `X-Razorpay-Signature`.
    # Reading only the Stripe header made EVERY Razorpay webhook fail
    # verification (400), so subscriptions never left TRIAL. The provider's
    # `parse_webhook` still does the actual HMAC check.
    signature = stripe_signature or razorpay_signature

    try:
        event = await provider.parse_webhook(payload=body, signature=signature or "")
    except Exception as exc:
        log.warning(
            "webhook.signature_invalid", provider=provider.name,
            error=str(exc), has_signature=bool(signature),
        )
        return JSONResponse(
            {"code": "invalid_signature", "message": "Webhook signature invalid", "details": {}},
            status_code=400,
        )

    log.info("webhook.received", provider=provider.name, event_id=event.id, type=event.type)

    with bypass_product(), bypass_tenant():
        # --- Stripe/mock-shaped invoice events -------------------------------
        #
        # `invoice.payment_succeeded`, `invoice.paid` and
        # `invoice.payment_failed` are **Stripe's** event names, and the two
        # branches below read the Stripe payload shape (`data["subscription"]`
        # as a flat id string). The mock driver mimics it, which is what the
        # integration tests and the Postman collection exercise.
        #
        # **Razorpay never sends `invoice.payment_failed`** — the API rejects
        # the name outright (`Invalid event name/names`). Under Razorpay a
        # failed charge arrives as `subscription.pending` (retrying) and then
        # `subscription.halted` (retries exhausted); both are handled in
        # `_SUBSCRIPTION_LIFECYCLE_HANDLERS`. So anyone auditing "do we notice
        # failed charges?" should read that map, not this branch.
        #
        # Kept rather than deleted, deliberately: the Stripe driver is a
        # supported driver in this repo (`providers/billing/stripe.py`), so
        # removing the branch would silently drop failed-invoice handling for
        # any product billing through it. Not gated on `provider.name` either,
        # because the mock driver — the one the test suite and the Postman
        # collection use — emits these same names.
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

        # Stripe/mock only — see the block comment above. Razorpay signals a
        # failed charge through `subscription.pending` / `.halted`.
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
        elif event.type in _SUBSCRIPTION_ACTIVE_EVENTS:
            # Razorpay subscription lifecycle: the customer authorized + paid on
            # the hosted checkout page (short_url) and Razorpay confirms back
            # here. Find the subscription by provider id and mark it ACTIVE.
            provider_sub_id = _extract_provider_subscription_id(event.data)
            sub = await db.scalar(
                select(Subscription).where(
                    Subscription.provider_subscription_id == provider_sub_id
                )
            )
            if sub is None:
                log.warning("webhook.subscription_missing", event_id=event.id,
                            provider_sub=provider_sub_id)
                return JSONResponse({"received": "true"}, status_code=200)
            set_current_product(sub.product_id)
            await billing_svc.handle_subscription_activated(db, subscription_id=sub.id)
            await audit.record(
                db, action="webhook.subscription_activated",
                resource_type="subscription", resource_id=sub.id,
                tenant_id=sub.tenant_id, product_id=sub.product_id,
                diff={"event_id": event.id, "type": event.type, "provider": provider.name},
            )

        elif event.type in _SUBSCRIPTION_LIFECYCLE_HANDLERS:
            provider_sub_id = _extract_provider_subscription_id(event.data)
            sub = await db.scalar(
                select(Subscription).where(
                    Subscription.provider_subscription_id == provider_sub_id
                )
            )
            if sub is None:
                log.warning("webhook.subscription_missing", event_id=event.id,
                            provider_sub=provider_sub_id)
                return JSONResponse({"received": "true"}, status_code=200)
            set_current_product(sub.product_id)
            await _SUBSCRIPTION_LIFECYCLE_HANDLERS[event.type](db, subscription_id=sub.id)
            await audit.record(
                db, action=f"webhook.{event.type.replace('.', '_')}",
                resource_type="subscription", resource_id=sub.id,
                tenant_id=sub.tenant_id, product_id=sub.product_id,
                diff={"event_id": event.id, "type": event.type, "provider": provider.name},
            )

        else:
            log.info("webhook.ignored", event_id=event.id, type=event.type)

    return JSONResponse({"received": "true"}, status_code=200)
