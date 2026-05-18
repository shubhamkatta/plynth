---
name: security
description: Apply the platform's security rules when adding auth, accepting input, exposing data, or handling secrets. Use whenever the user asks for "auth", "permissions", "validate", "secrets", "sanitize", or anything touching the boundary. Don't use for purely internal refactors.
---

# Security rules

## Auth

- Passwords: Argon2id via `app.core.security.hash_password`. **Never** call
  `bcrypt` / `hashlib` / `pbkdf2` directly.
- JWTs: always issued through `issue_token(...)`; verified with
  `decode_token(..., expected_type=...)`. Always pass `expected_type`.
- Refresh tokens are tracked server-side in `refresh_tokens` so they can be
  revoked on logout / password change. Don't return raw refresh tokens in URLs
  or logs.

## Permission checks

- Every mutating route must have `Depends(require_permission("..."))`.
- Read endpoints that expose tenant-scoped data still need `CurrentUser` —
  the tenant filter only works inside the request's tenant context.
- Don't roll your own permission checks. Use the helper.

## Tenant isolation

- Never query a tenant-scoped table without going through `TenantRepository`,
  unless you explicitly `with bypass_tenant():` and audit the access.
- Code review heuristic: `grep -n bypass_tenant` should return a small,
  known set of files (login, webhooks, admin tooling).

## Input validation

- Use Pydantic schemas for every request body / query parameter. Don't
  manually parse JSON.
- Use `EmailStr`, `constr(pattern=...)`, `conint(ge=...)` etc — not raw `str`.
- Files / uploads: cap size at the ASGI level (uvicorn `--limit-max-requests`
  is a poor man's defence; use a proper proxy in front).

## Secrets

- Read from `app.core.config.settings`, never `os.environ` directly.
- Never log secrets, JWTs, payment tokens, or PII. structlog's
  `EventRenamer` can blacklist keys — extend it before logging request bodies.

## Webhooks

- Always verify the signature (`provider.parse_webhook` does this).
- Reject unknown event types silently — providers can add new ones.
- Off-load heavy work to arq; return 200 quickly so providers don't retry.

## DB

- All queries use parametrised SQLAlchemy — no string interpolation into SQL.
- For raw SQL (rare), use `text(...)` with `:params`.
- Cascading deletes are explicit (`ondelete="CASCADE"`) — never rely on ORM
  cascade alone for FK behaviour at the DB.

## Error reporting

- Never echo raw exception text to the client in production. The global
  handlers in `app/core/error_handlers.py` already produce a sanitised
  envelope; stick with them.
- Security-sensitive failures (failed login, signature mismatch, permission
  denied) must be logged at `warning` and — where a tenant context exists —
  written to the audit log. See `/error-handling-and-audit`.

## Things to avoid

- Disabling JWT signature verification.
- Returning ORM objects directly from routes without a `response_model` (leaks
  internal columns).
- Wrapping `verify_password` outputs in caching — Argon2's cost is the point.
- Custom CORS configs that include `*` with `allow_credentials=True` — modern
  browsers reject this anyway.
- Using `eval`, `pickle.loads` on external input. Ever.
- Leaking secrets / JWTs / payment tokens / full PII into logs or audit
  diffs. structlog kwargs are searchable in your log store — assume every
  field is queried by ops.
