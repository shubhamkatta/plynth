# Credits / Metered Usage

## Why a ledger

Three properties we need:
- **Auditability** — answer "where did 47 credits go?" in O(1) query.
- **Idempotency** — webhook retries / client retries must not double-charge.
- **Atomicity under concurrency** — two requests at the same time must not
  both succeed past the balance.

A wallet + append-only ledger gives all three.

## Schema

- `credit_wallets` — one row per (tenant, feature_key). Holds current balance.
- `credit_ledger` — one row per movement: GRANT / DEBIT / REFUND / EXPIRY /
  ADJUSTMENT. Signed `amount` + `balance_after` snapshot.

`balance = sum(ledger.amount where wallet_id = w.id)` is always true. Wallet is
a cache for fast reads but reconcilable from the ledger.

## Atomic consume

```python
async with session_scope() as db:
    await credit.consume(
        db, tenant_id=..., feature_key="credits.ai_completion",
        amount=Decimal("1"), reason="completion",
        reference=f"req:{request_id}",  # dedup key
    )
```

Internally:
1. `SELECT … FOR UPDATE` locks the wallet row.
2. If a ledger entry with `reference` already exists, return early (idempotent).
3. If `balance < amount`, raise `InsufficientCredits` (HTTP 402).
4. Append the ledger entry, update the wallet, commit atomically.

## Plan-driven grants

`PlanFeature.credit_amount`, if set, is granted at every billing period start.
This is wired in:
- `start_trial` — grants on day 0.
- `purchase` — grants for the new period.
- (TODO) period-renewal webhook handler should grant at `invoice.paid` for the
  new period start. Use `reference=f"period:{sub.id}:{period_start.date()}"`
  so retries dedupe.

## Resets

`credit.reset_period` zeros the wallet and writes an EXPIRY entry. Schedule it
from the period-renewal webhook **after** the renewal grant so end-users see
their fresh balance immediately.

## Limits vs credits

`PlanFeature` has two knobs:
- `limit_value` — hard cap on instantaneous usage (e.g. seats, GB storage).
  Enforced in the feature's own code via a count query.
- `credit_amount` — bucket that drains over time. Enforced by `consume()`.

Use `limit_value` for capacity, `credit_amount` for metered actions.
