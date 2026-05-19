# Billing & Subscriptions

## State machine

```
            ┌───────────────┐
            │     trial     │ ── trial_end ──▶ active (if paid) | suspended (if not)
            └───────────────┘
                    │ purchase
                    ▼
            ┌───────────────┐  cancel(at_period_end=False)
            │    active     │ ─────────────────────────────▶ cancelled
            └─────┬─────────┘
                  │ invoice.payment_failed (attempt < 3)
                  ▼
            ┌───────────────┐
            │   past_due    │ ── attempt ≥ 3 ──┐
            └─────┬─────────┘                  │
                  │ payment_succeeded          ▼
                  │                       ┌─────────────┐
                  └──── reactivate ◀──────│    grace    │
                                          └─────┬───────┘
                                                │ grace_ends_at ≤ now
                                                ▼
                                          ┌─────────────┐
                                          │  suspended  │   (access cut)
                                          └─────────────┘
```

`Subscription.has_access` returns True for trial, active, past_due, grace.

## Upgrade / downgrade

`POST /subscription/change { plan_code, proration }`:
1. Calls `provider.change_subscription` (Stripe handles proration).
2. Swaps `plan_id` locally.
3. Credits for the new plan are issued on the **next** period start, not
   immediately — prevents double-granting on mid-period upgrades.

## Provider abstraction

`app/providers/billing/base.BillingProvider` defines:
- `ensure_customer`, `create_subscription`, `change_subscription`,
  `cancel_subscription`, `retry_invoice`, `parse_webhook`.

To add a new provider (Paddle, Lemon Squeezy, …):

1. Implement the interface under `app/providers/billing/<name>.py`.
2. Wire it in `factory.get_billing_provider`.
3. Set `BILLING_PROVIDER=<name>` in env.
4. Plans reference provider-specific IDs in `plans.provider_refs` JSONB
   (`{"stripe": "price_xxx", "paddle": "pri_xxx"}`).

## Webhooks

`POST /api/v1/webhooks/billing`:
- Always verify the signature header (`Stripe-Signature`). Provider's
  `parse_webhook` does it.
- Handler is intentionally thin: persists invoice + flips subscription state.
  Heavy work belongs in arq jobs.

## Grace period & suspension

`task_check_grace_period` runs hourly:
- Subscriptions in `grace` with `grace_ends_at <= now()` → `suspended`.

`task_send_payment_reminders` runs daily 09:00 UTC:
- Sends reminders at -3 / 0 / +3 / +7 days relative to invoice due date.
- Per-(invoice, offset) idempotency via Redis SETNX.

## Idempotency

Mutating billing endpoints (`/purchase`, `/change`) accept an
`Idempotency-Key` header. Provider calls forward it. Server-side dedupe is via
the `idempotency_keys` table — implement enforcement in the route by hashing
the request body and checking before executing.
