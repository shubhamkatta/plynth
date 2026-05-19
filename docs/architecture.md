# Architecture

## Layering

```
api/         FastAPI routers — HTTP shape only, no business rules
schemas/     Pydantic DTOs for I/O validation
services/    Business logic + transactional boundaries
repositories/  DB access helpers (tenant-scoped)
models/      SQLAlchemy ORM
providers/   External adapters (billing, notifications) behind interfaces
middleware/  Cross-cutting concerns (request ID, rate limiting)
core/        Config, security, logging, deps, exceptions, tenant context
tasks/       Background jobs (arq)
```

**Rule**: dependencies flow downward only.
`api → services → repositories → models`. Services may use providers.
Models never import from services. Repositories never import schemas.

## Request lifecycle

1. ASGI accepts the request.
2. `RequestContextMiddleware` binds `request_id` to structlog.
3. `RateLimitMiddleware` consults Redis (sliding window).
4. The route runs its dependencies, in order:
   - `get_db` opens a transactional session.
   - `resolve_product` reads `X-Product-Slug` (if present), resolves slug
     → UUID via Redis cache, sets `current_product_id`.
   - For public routes, `RequireProduct` errors out when no header.
   - For authenticated routes, `get_current_user` validates the JWT,
     pulls `pid` + `tid` from the claims, sets both context vars, and
     verifies the header (if also present) matches the JWT.
   - `require_permission("...")` runs the RBAC check.
5. Route → service → repository → DB. `TenantRepository` applies
   `WHERE product_id = :pid AND tenant_id = :tid` to every query.
6. On clean exit, the session commits; on raise, it rolls back.
7. `AppError` handlers map exceptions to JSON `{code, message, details}`.

## Transactions

- One transaction per HTTP request, opened by `get_db`.
- Background jobs use `session_scope()` per logical unit of work.
- Webhook handlers wrap their side-effects in `bypass_tenant()` because the
  inbound request has no authenticated user.

## Concurrency

- Credit consumption uses `SELECT … FOR UPDATE` on the wallet row to serialise
  debits. Reference-based deduplication handles retries.
- Idempotency keys are first-class for billing endpoints
  (`Idempotency-Key` header → `idempotency_keys` table).

## Errors

Every exception flows through `app/core/error_handlers.register_handlers`,
which produces a uniform JSON envelope and emits a structured log event.

| Exception              | Status | Log level    | Code on the wire        |
| ---------------------- | ------ | ------------ | ----------------------- |
| `AppError` subclass    | 4xx/5xx| warn / error | `exc.code`              |
| `RequestValidationError`| 422   | info         | `validation_failed`     |
| `StarletteHTTPException`| 4xx/5xx| info / error | derived from `detail`   |
| `IntegrityError`       | 409    | warning      | `conflict`              |
| `OperationalError`     | 503    | error        | `service_unavailable`   |
| `SQLAlchemyError`      | 500    | exception    | `internal_error`        |
| anything else          | 500    | exception    | `internal_error`        |

Wire envelope:

```json
{ "code": "not_found", "message": "user 9b2…", "details": {} }
```

Services raise typed exceptions from `app/core/exceptions.py`. Routers don't
translate to HTTP themselves. Webhook handlers explicitly catch
signature-parse failures and return 400 — never let providers retry on a
500.

## Logging

- **structlog** JSON to stdout. One `logger` per module
  (`structlog.get_logger("auth")`).
- `RequestContextMiddleware` binds `request_id`, `method`, `path` to every
  log line of the request.
- `get_current_user` adds `user_id` and `tenant_id` once authenticated.
- Severity is for *operators*: `info` = milestone, `warning` = recoverable,
  `error` = needs attention, `exception` = unhandled with stack.
- Never log secrets, JWTs, payment tokens, raw PII.

## Audit

`app/services/audit.py` is the only writer to `audit_log`.

Two entry points:

- **`audit.record(...)`** — explicit per-action call. Use when no
  before/after wrap is needed.
- **`audit.audit_action(...)`** — async context manager. Writes the audit
  row on clean exit; on raise, logs `action.failed` with full context and
  re-raises (no row, since the surrounding transaction will roll back).

Write an entry for every state change. Action name is `<resource>.<action>`
lowercase snake (`user.activate`, `subscription.upgrade`). Don't audit
reads — that's what request logs are for.

`audit.record` is a no-op when no tenant context is active; truly
platform-level events are logged but not stored. To audit a cross-tenant
admin action, pass `tenant_id=` explicitly.

## Why these choices

- **FastAPI**: async, OpenAPI baked in, smallest cognitive overhead.
- **SQLAlchemy 2.0 async**: typed, mature, ergonomic with `Mapped[…]`.
- **Postgres**: row-level security available if/when you want defence in
  depth on top of `TenantRepository`.
- **arq over Celery**: 1/10 the dependencies + ops surface, more than enough
  for reminders / sweeps. Swap if you need Celery features.
- **Argon2id**: OWASP-recommended over bcrypt for new systems.
