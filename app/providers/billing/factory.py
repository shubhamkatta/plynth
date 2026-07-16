from functools import lru_cache

from app.core.config import settings
from app.providers.billing.base import BillingProvider
from app.providers.billing.mock import MockBillingProvider


@lru_cache(maxsize=1)
def get_billing_provider() -> BillingProvider:
    if settings.billing_provider == "stripe":
        # Imported lazily so the stripe SDK isn't loaded in mock-only environments.
        from app.providers.billing.stripe import StripeBillingProvider
        return StripeBillingProvider()
    if settings.billing_provider == "razorpay":
        # Lazy import keeps httpx-only Razorpay out of stripe/mock environments.
        from app.providers.billing.razorpay import RazorpayBillingProvider
        return RazorpayBillingProvider()
    return MockBillingProvider()
