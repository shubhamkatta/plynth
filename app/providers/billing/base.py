"""Provider-neutral DTOs + interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ProviderCustomer:
    id: str
    email: str


@dataclass(slots=True)
class ProviderSubscription:
    id: str
    customer_id: str
    price_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool


@dataclass(slots=True)
class ProviderInvoice:
    id: str
    customer_id: str
    subscription_id: str | None
    amount_cents: int
    currency: str
    status: str
    hosted_url: str | None
    issued_at: datetime
    due_at: datetime


@dataclass(slots=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(slots=True)
class WebhookEvent:
    id: str
    type: str
    data: dict[str, Any]


class BillingProvider(ABC):
    name: str

    @abstractmethod
    async def ensure_customer(self, *, tenant_id: str, email: str) -> ProviderCustomer: ...

    @abstractmethod
    async def create_subscription(
        self,
        *,
        customer_id: str,
        price_id: str,
        trial_days: int,
        payment_method_token: str | None,
        idempotency_key: str | None,
    ) -> ProviderSubscription: ...

    @abstractmethod
    async def change_subscription(
        self,
        *,
        subscription_id: str,
        new_price_id: str,
        proration: bool,
        idempotency_key: str | None,
    ) -> ProviderSubscription: ...

    @abstractmethod
    async def cancel_subscription(
        self, *, subscription_id: str, at_period_end: bool
    ) -> ProviderSubscription: ...

    @abstractmethod
    async def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent: ...

    @abstractmethod
    async def retry_invoice(self, *, invoice_id: str) -> ProviderInvoice: ...
