---
name: error-handling-and-audit
description: Raise the right exception, log at the right severity, and write an audit entry for every state change. Use whenever you add or modify a service / route / job / webhook — anything that can fail or that mutates state. Don't use for pure read paths with no failure modes.
---

# Error handling & audit

Three rules. They are non-negotiable in this codebase.

1. **Raise typed exceptions, never bare `HTTPException`.**
   Subclasses of `AppError` in `app/core/exceptions.py` carry a stable
   machine `code`, HTTP `status_code`, and `details` dict. The global
   handler in `app/core/error_handlers.py` converts them to the uniform
   JSON envelope `{code, message, details}`.

2. **Log unhandled paths through the global handlers — never `try / except
   Exception: pass`.** The handler in `register_handlers()` already emits
   structured events at the right severity. Don't swallow.

3. **Every state change writes an audit entry.** Use
   `audit.record(...)` for one-shot calls or the `audit.audit_action(...)`
   async context manager for blocks. No mutating service path ships without
   one.

## Exception types — pick the right one

| Raise                  | When                                                    | HTTP |
| ---------------------- | ------------------------------------------------------- | ---- |
| `NotFound`             | A queried resource doesn't exist for this tenant        | 404  |
| `Conflict`             | UNIQUE collision, state conflict (e.g. already cancelled)| 409 |
| `ValidationFailed`     | Business-rule rejection beyond Pydantic shape           | 422  |
| `Unauthorized`         | Bad / missing / expired credentials                     | 401  |
| `Forbidden`            | Authenticated but lacks permission                      | 403  |
| `RateLimited`          | Quota / throttle exceeded                               | 429  |
| `PaymentRequired`      | Subscription suspended, billing required                | 402  |
| `InsufficientCredits`  | Wallet doesn't have enough credits                      | 402  |

Wrong choice creates a quietly broken contract — clients can't differentiate
"not found" from "no permission".

## Global handlers — what's already wired

`app/core/error_handlers.register_handlers`:

- `AppError` → JSON envelope; `warning` for 4xx, `error` for 5xx.
- `RequestValidationError` → 422, `info` (just bad input).
- `IntegrityError` → 409 `conflict`, `warning`.
- `OperationalError` → 503 `service_unavailable`, `error`.
- `SQLAlchemyError` (other) → 500 `internal_error`, `exception` with stack.
- Anything else → 500 `internal_error`, `exception` with stack.

Every event carries `request_id`, `method`, `path`, plus `user_id` +
`tenant_id` once `get_current_user` has run.

You should rarely need to add a new handler. If you do, register it in
`register_handlers()` so the behaviour stays centralised.

## Logging conventions

- **structlog only**, never `print`. `log = structlog.get_logger("name")`.
- Use `log.info` for milestones, `log.warning` for recoverable problems,
  `log.error` for things that need an operator, `log.exception` to capture
  a stack trace from inside an `except` block.
- Pass attributes as kwargs (`log.info("payment.succeeded",
  invoice_id=str(i.id))`), never f-string them into the message — they
  become first-class searchable fields.
- Never log secrets, JWTs, payment tokens, raw passwords, or full PII.
  Email is fine; payload bodies are not.

## Audit — what to record

Write an audit entry whenever you mutate persistent state that matters
later for compliance, support, or debugging:

- Auth: register, login, login_failed, logout, password_change.
- Tenant: create, activate, deactivate, delete.
- User: invite, activate, deactivate, delete.
- Role: create, update, assign (`UserRole` change).
- Subscription: trial_started, purchase, upgrade, downgrade, cancel,
  past_due, grace_started, suspended, reactivated.
- Credits: period_reset, manual grant or adjustment. Routine `consume`
  events live in the ledger, not the audit log.
- Webhook receipt: one entry per accepted event.

Action naming: `<resource>.<action>` lowercase snake — e.g.
`subscription.upgrade`, `user.password_change`. Stable strings; queries
depend on them.

## Two APIs for audit

### `audit.record(...)`

Use when you've already done the work or there's no clean "before / after"
pair:

```python
await audit.record(
    db, action="user.deactivate", actor_user_id=actor.id,
    resource_type="user", resource_id=target.id,
)
```

### `audit.audit_action(...)`  (context manager)

Use for a multi-step action — captures actor/resource once, succeeds on
clean exit, logs failure + re-raises on exception:

```python
async with audit.audit_action(
    db, action="role.create", actor_user_id=user.id, resource_type="role",
    diff={"name": payload.name},
) as extras:
    role = await create_role(...)
    extras["role_id"] = str(role.id)
```

On exception inside the block:
- A structured `action.failed` warning is logged with the action +
  resource context and the exception type.
- No audit row is written (rolled-back transactions must not look
  successful in the log).

## Mistakes to avoid

- **Re-raising as `HTTPException`.** Just let the typed exception bubble —
  the handler already does the conversion.
- **Calling `audit.record` outside the transaction.** If the request rolls
  back, the audit row rolls back with it (good). Don't post-commit audit.
- **Logging the entire request body.** Strip secrets. Prefer structured
  fields over dumping payloads.
- **Generic `Exception` catches in business code.** If you need to handle a
  specific error (e.g. `IntegrityError` for an optimistic upsert), catch
  exactly that. Everything else should bubble to the global handler.
- **Treating webhook signature failures as 500.** They're 400 — providers
  will retry forever otherwise. The handler in `webhooks.py` shows the
  pattern.
- **Auditing reads.** Audit is for state changes. Reads belong in access
  logs (e.g. add `audit:read` only if compliance requires it).

## Reviewer checklist

- [ ] Every mutating service path emits an audit entry.
- [ ] Failure paths raise an `AppError` subclass with the right code.
- [ ] No bare `try / except Exception: pass`.
- [ ] No `print`, no f-strings in log messages; kwargs only.
- [ ] No secret values in logs or audit `diff`.
- [ ] Webhook handlers return 200 (or 400 on signature mismatch), never
      raise into the handler.
