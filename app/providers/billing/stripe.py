"""Stripe driver. Thin wrapper around `stripe` SDK.

Two important conventions:
- pass `idempotency_key` on every mutating call to defend against retries.
- the webhook handler MUST verify the signature using
  `stripe.Webhook.construct_event` — never trust raw bodies.
"""

from datetime import UTC, datetime
from typing import Any, cast

import stripe

from app.core.config import settings
from app.providers.billing.base import (
    BillingProvider,
    ProviderCustomer,
    ProviderInvoice,
    ProviderSubscription,
    WebhookEvent,
)


def _ts(ts: int | None) -> datetime:
    return datetime.fromtimestamp(ts or 0, tz=UTC)


class StripeBillingProvider(BillingProvider):
    name = "stripe"

    def __init__(self) -> None:
        if not settings.stripe_api_key:
            raise RuntimeError("STRIPE_API_KEY missing")
        stripe.api_key = settings.stripe_api_key

    async def ensure_customer(self, *, tenant_id: str, email: str) -> ProviderCustomer:
        # Look up by metadata first; create if absent. (Use Search API in prod.)
        existing = await stripe.Customer.search_async(
            query=f'metadata["tenant_id"]:"{tenant_id}"'
        )
        if existing.data:
            cust = existing.data[0]
        else:
            cust = await stripe.Customer.create_async(
                email=email, metadata={"tenant_id": tenant_id}
            )
        return ProviderCustomer(id=cust.id, email=cust.email or email)

    async def create_subscription(
        self,
        *,
        customer_id: str,
        price_id: str,
        trial_days: int,
        payment_method_token: str | None,
        idempotency_key: str | None,
    ) -> ProviderSubscription:
        kwargs: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "payment_behavior": "default_incomplete",
            "expand": ["latest_invoice.payment_intent"],
        }
        if trial_days:
            kwargs["trial_period_days"] = trial_days
        if payment_method_token:
            kwargs["default_payment_method"] = payment_method_token

        sub = await stripe.Subscription.create_async(**kwargs, idempotency_key=idempotency_key)
        return self._sub(sub)

    async def change_subscription(
        self,
        *,
        subscription_id: str,
        new_price_id: str,
        proration: bool,
        idempotency_key: str | None,
    ) -> ProviderSubscription:
        current = await stripe.Subscription.retrieve_async(subscription_id)
        item_id = current["items"]["data"][0]["id"]
        sub = await stripe.Subscription.modify_async(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="create_prorations" if proration else "none",
            idempotency_key=idempotency_key,
        )
        return self._sub(sub)

    async def cancel_subscription(
        self, *, subscription_id: str, at_period_end: bool
    ) -> ProviderSubscription:
        if at_period_end:
            sub = await stripe.Subscription.modify_async(
                subscription_id, cancel_at_period_end=True
            )
        else:
            sub = await stripe.Subscription.cancel_async(subscription_id)
        return self._sub(sub)

    async def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        # `construct_event` is untyped in the stripe stubs; the cast keeps the
        # strict-mode "no-untyped-call" check from firing without losing the
        # runtime signature-verification behaviour.
        construct = cast(Any, stripe.Webhook.construct_event)
        event = construct(payload, signature, settings.stripe_webhook_secret)
        return WebhookEvent(id=event["id"], type=event["type"], data=event["data"]["object"])

    async def retry_invoice(self, *, invoice_id: str) -> ProviderInvoice:
        inv = await stripe.Invoice.pay_async(invoice_id)
        # The Stripe SDK types are loose: `customer` may be str | Customer | None,
        # `subscription` was removed from the typed surface in newer SDKs but is
        # still present at runtime, and `status` is typed as a Literal | None.
        # Normalise them all to strings here; raise loudly if a required field
        # is genuinely missing.
        raw_customer = getattr(inv, "customer", None)
        if raw_customer is None:
            raise RuntimeError(f"stripe invoice {inv.id} has no customer")
        customer_id = raw_customer if isinstance(raw_customer, str) else raw_customer.id

        raw_subscription = getattr(inv, "subscription", None)
        subscription_id: str | None
        if raw_subscription is None:
            subscription_id = None
        elif isinstance(raw_subscription, str):
            subscription_id = raw_subscription
        else:
            subscription_id = raw_subscription.id

        if inv.status is None:
            raise RuntimeError(f"stripe invoice {inv.id} has no status")

        return ProviderInvoice(
            id=inv.id, customer_id=customer_id, subscription_id=subscription_id,
            amount_cents=inv.amount_due, currency=inv.currency.upper(),
            status=inv.status, hosted_url=inv.hosted_invoice_url,
            issued_at=_ts(inv.created), due_at=_ts(inv.due_date or inv.created),
        )

    @staticmethod
    def _sub(sub: Any) -> ProviderSubscription:
        return ProviderSubscription(
            id=sub["id"],
            customer_id=sub["customer"],
            price_id=sub["items"]["data"][0]["price"]["id"],
            status=sub["status"],
            current_period_start=_ts(sub["current_period_start"]),
            current_period_end=_ts(sub["current_period_end"]),
            cancel_at_period_end=sub["cancel_at_period_end"],
        )
