"""Which provider speaks which webhook dialect (queue T-034).

`parse_webhook` returns the provider's **own** event name — `body["event"]`
for Razorpay, `event["type"]` for Stripe — so the two dialects coexist in one
handler and it is easy to read a branch as coverage it does not give.

T-034 reported `invoice.payment_failed` as dead code, because Razorpay rejects
that event name outright (`Invalid event name/names` — it is Stripe's). The
report is right about Razorpay and wrong about "dead": the Stripe driver is a
supported driver in this repo and the mock driver emits the same names, which
is what the integration tests and the Postman collection exercise. Deleting
the branch would silently drop failed-invoice handling for both.

So the branch stays, documented as Stripe/mock dialect, and this pins the
claim that matters to anyone asking "do we notice failed charges?" — under
Razorpay the answer lives in the subscription lifecycle map, not there.
"""

from app.api.v1.webhooks import (
    _SUBSCRIPTION_ACTIVE_EVENTS,
    _SUBSCRIPTION_LIFECYCLE_HANDLERS,
)


def test_razorpay_failure_states_are_handled_as_subscription_events():
    """`subscription.pending` (retrying) and `.halted` (retries exhausted) are
    how Razorpay expresses a failed charge. Both must be mapped, or a failing
    card is invisible under the only provider actually in use."""
    assert "subscription.pending" in _SUBSCRIPTION_LIFECYCLE_HANDLERS
    assert "subscription.halted" in _SUBSCRIPTION_LIFECYCLE_HANDLERS
    assert "subscription.cancelled" in _SUBSCRIPTION_LIFECYCLE_HANDLERS


def test_invoice_payment_failed_is_not_a_razorpay_lifecycle_event():
    """It is Stripe's name. If it ever appears in the Razorpay-dialect map,
    someone has mistaken the Stripe branch for Razorpay coverage."""
    assert "invoice.payment_failed" not in _SUBSCRIPTION_LIFECYCLE_HANDLERS
    assert "invoice.payment_failed" not in _SUBSCRIPTION_ACTIVE_EVENTS


def test_mandate_authorization_does_not_activate_a_trial():
    """`subscription.authenticated` fires during a card-on-file trial, before
    any money moves, so it must stay out of the activating set — otherwise the
    status label flips TRIAL → ACTIVE before the first charge."""
    assert "subscription.authenticated" in _SUBSCRIPTION_LIFECYCLE_HANDLERS
    assert "subscription.authenticated" not in _SUBSCRIPTION_ACTIVE_EVENTS
