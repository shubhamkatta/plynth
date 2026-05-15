"""In-memory mock — used for local dev + tests. Never use in production."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.providers.billing.base import (
    BillingProvider,
    ProviderCustomer,
    ProviderInvoice,
    ProviderSubscription,
    WebhookEvent,
)


class MockBillingProvider(BillingProvider):
    name = "mock"

    def __init__(self) -> None:
        self._subscriptions: dict[str, ProviderSubscription] = {}

    async def ensure_customer(self, *, tenant_id: str, email: str) -> ProviderCustomer:
        return ProviderCustomer(id=f"mock_cus_{tenant_id}", email=email)

    async def create_subscription(
        self,
        *,
        customer_id: str,
        price_id: str,
        trial_days: int,
        payment_method_token: str | None,
        idempotency_key: str | None,
    ) -> ProviderSubscription:
        now = datetime.now(UTC)
        sub = ProviderSubscription(
            id=f"mock_sub_{uuid4().hex[:12]}",
            customer_id=customer_id,
            price_id=price_id,
            status="trialing" if trial_days else "active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            cancel_at_period_end=False,
        )
        self._subscriptions[sub.id] = sub
        return sub

    async def change_subscription(
        self, *, subscription_id, new_price_id, proration, idempotency_key
    ) -> ProviderSubscription:
        sub = self._subscriptions[subscription_id]
        sub.price_id = new_price_id
        return sub

    async def cancel_subscription(self, *, subscription_id, at_period_end) -> ProviderSubscription:
        sub = self._subscriptions[subscription_id]
        if at_period_end:
            sub.cancel_at_period_end = True
        else:
            sub.status = "canceled"
        return sub

    async def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        # Echo the payload as-is — tests construct deterministic events.
        import json
        body = json.loads(payload)
        return WebhookEvent(id=body.get("id", "evt_mock"), type=body["type"], data=body.get("data", {}))

    async def retry_invoice(self, *, invoice_id: str) -> ProviderInvoice:
        now = datetime.now(UTC)
        return ProviderInvoice(
            id=invoice_id, customer_id="mock_cus", subscription_id=None,
            amount_cents=0, currency="USD", status="paid", hosted_url=None,
            issued_at=now, due_at=now,
        )
