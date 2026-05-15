"""Billing provider abstraction.

To add a provider:
1. Subclass `BillingProvider` in `providers/billing/<name>.py`.
2. Register it in `get_billing_provider()`.
3. Map your payloads to the provider-neutral DTOs declared below.

The platform never branches on provider in business logic — it only calls the
interface.
"""

from app.providers.billing.base import (
    BillingProvider,
    CheckoutSession,
    ProviderCustomer,
    ProviderInvoice,
    ProviderSubscription,
    WebhookEvent,
)
from app.providers.billing.factory import get_billing_provider

__all__ = [
    "BillingProvider",
    "CheckoutSession",
    "ProviderCustomer",
    "ProviderInvoice",
    "ProviderSubscription",
    "WebhookEvent",
    "get_billing_provider",
]
