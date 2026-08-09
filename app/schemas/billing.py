from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    """Start a paid subscription checkout for the caller's tenant."""

    plan_code: str


class CheckoutResponse(BaseModel):
    """Result of POST /billing/checkout.

    - Paid plan → ``url`` is the provider's hosted authorization/checkout page
      (Razorpay ``short_url``) the site redirects the browser to, and
      ``subscription_id`` is the provider subscription id.
    - Free/$0 plan → ``url`` is ``null`` and ``status`` is ``"active"``; the
      tenant is already subscribed, so the site can land them straight in the
      app with no payment step.
    """

    url: str | None = None
    subscription_id: str | None = None
    status: str | None = None
