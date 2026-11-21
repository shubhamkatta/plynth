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

A `trial` that never converts is ended by `task_expire_trials` (see below):
`trial_end + TRIAL_EXPIRY_BUFFER_DAYS` passed with no `subscription.charged` /
`activated` webhook → `expired` (access cut). A late charge webhook revives it
to `active`.

## Free trial (card-on-file / UPI-AutoPay mandate)

Paid signup is a **mandate-first free trial**: at checkout the customer
authorizes a recurring mandate (card or UPI-AutoPay on Razorpay's hosted
`short_url`) but is **not charged**. The first deduction happens automatically
at trial end.

`subscription.purchase` (used by both `/subscription/purchase` and
`/billing/checkout`) implements this:

- **Free/$0 plan** → no mandate, no charge; subscription is `active` immediately
  (`trial_days=0`).
- **Paid plan** → the provider subscription is created with a **future
  `start_at`** (the neutral `trial_days` arg; Razorpay `start_at = now +
  trial_days*86400`). Local status stays `trial` with `trial_end = start_at`;
  the `subscription.charged/activated` webhook flips it to `active` after the
  first charge lands.

`trial_days` is derived from the plan (`plan.trial_days`, else
`settings.default_trial_days` = 14). **Single-trial reconciliation:** if
`register → start_trial` already opened a local trial, `purchase` defers the
first charge to that **existing** `trial_end` (remaining days) instead of
stacking a second 14-day trial — the customer sees one ~14-day trial and is
charged once, after it.

Timeline (paid register → checkout):

```
register (t0)       → local trial, trial_end = t0 + 14d
checkout (t0..t1)   → Razorpay sub, start_at = trial_end (mandate authorized,
                      NOT charged); local stays trial, provider ids attached
trial_end (~t0+14d) → Razorpay raises the first invoice, charges ONCE →
                      subscription.charged webhook → active
```

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

Razorpay lifecycle events handled (beyond `activated` / `charged`):

| Event | Effect |
| --- | --- |
| `subscription.authenticated` | records `meta.mandate_authorized_at`; status stays `trial`; surfaced as `mandate_authorized` on `GET /subscription` |
| `subscription.pending` | charge failed, Razorpay retrying → `past_due` (from `active`/`trial`) |
| `subscription.halted` | retries exhausted → `grace` |
| `subscription.cancelled` | → `cancelled` (idempotent). A later `charged` never revives a cancelled sub |

`payment.failed` is intentionally ignored (no subscription id in payload).

`POST /api/v1/webhooks/billing`:
- Always verify the signature header (`Stripe-Signature`, or `X-Razorpay-Signature` for Razorpay). Provider's
  `parse_webhook` does it.
- Handler is intentionally thin: persists invoice + flips subscription state.
  Heavy work belongs in arq jobs.

## Grace period & suspension

`task_check_grace_period` runs hourly:
- Subscriptions in `grace` with `grace_ends_at <= now()` → `suspended`.

## Trial expiry

`task_expire_trials` runs hourly at `:15`:
- Subscriptions in `trial` with `trial_end <= now() - TRIAL_EXPIRY_BUFFER_DAYS`
  (default 1) → `expired`, audited as `subscription.trial_expired`. The buffer
  absorbs the gap between Razorpay's first charge and its webhook.

`task_send_payment_reminders` runs daily 09:00 UTC:
- Sends reminders at -3 / 0 / +3 / +7 days relative to invoice due date.
- Per-(invoice, offset) idempotency via Redis SETNX.

## Idempotency

Mutating billing endpoints (`/purchase`, `/change`) accept an
`Idempotency-Key` header. Provider calls forward it. Server-side dedupe is via
the `idempotency_keys` table — implement enforcement in the route by hashing
the request body and checking before executing.
