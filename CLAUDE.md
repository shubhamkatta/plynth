# Working in this repo

This is a reusable multi-tenant **multi-product** SaaS backend scaffold. It
hosts many independent SaaS products on a single deployment — each with its
own tenants, users, plans, subscriptions, credits, audit. Auth, RBAC,
billing, audit, etc. are an **independent platform layer**; products built
on top live under `app/products/<name>/`.

## Available skills

Invoke via `/skill-name` or trust the matcher:

- `/add-feature` — new vertical slice (model + schema + service + router).
- `/add-endpoint` — single new HTTP endpoint on an existing router.
- `/add-migration` — generate, review, ship an Alembic migration.
- `/testing` — write unit / integration tests.
- `/security` — security guardrails for auth, input, secrets, webhooks.
- `/multi-tenant` — tenant-isolation rules; required reading for anything DB.
- `/multi-product` — product-isolation rules; required reading for anything DB.
- `/error-handling-and-audit` — typed exceptions, structured logging,
  audit-on-every-mutation. Required reading for any service or route work.

See `.claude/skills/*/SKILL.md` for the full text.

## Architecture rules

- Layers flow downward: `api → services → repositories → models`.
- Routers are dumb adapters. Business logic lives in services.
- Schemas (Pydantic) never touched by models; models (SQLAlchemy) never
  touched by routers.
- One transaction per HTTP request. Webhooks + jobs use `session_scope()`.
- All async. No sync DB calls anywhere in `app/`.

## Product + tenant scoping

- Every domain table has `product_id NOT NULL` and (where applicable)
  `tenant_id NOT NULL`. `Permission` is the one shared global catalog.
- Every read/write goes through `TenantRepository` (dual filter on
  `(product_id, tenant_id)`).
- Cross-product / cross-tenant access goes through explicit
  `with bypass_product():` and `with bypass_tenant():`. Reviewed line by
  line. Grep for them.
- Public endpoints use `RequireProduct` dependency (reads
  `X-Product-Slug` header). Authenticated endpoints derive product from
  the JWT `pid` claim. Header + JWT must agree.
- Parent → child access: a user can scope a request to a direct child
  with `X-Acting-Tenant-Slug: <child-slug>`. Three gates approve:
  hierarchy (`parent_id == user.tenant_id`), config flags
  (`Product.settings.features.allow_parent_child_access` +
  `Tenant.settings.allow_child_access`, both default true), and RBAC
  (`tenants:act_as_child` permission in home OR explicit
  `UserRole.scope_tenant_id == target`). Routes filter on
  `current_tenant_id() or user.tenant_id` — never `user.tenant_id`
  alone. `audit_log.acting_from_tenant_id` is auto-populated.

## RBAC

- Permissions: `resource:action` global codes, wildcards `*:*` and
  `users:*` allowed.
- Roles are per-product (system roles seeded on product creation).
- Mutating routes always have `Depends(require_permission("..."))`.
- Add new permissions in `services/rbac.SYSTEM_PERMISSIONS`, re-seed.

## Billing

- Provider-agnostic. Driver in `providers/billing/<name>.py` implementing
  `BillingProvider`.
- Subscription lifecycle: trial → active → past_due → grace → suspended /
  cancelled. State machine in `docs/billing.md`.
- Always honour `Idempotency-Key` on mutating billing endpoints.
- Webhooks derive product from the persisted subscription, no header.

## Credits

- Wallet + append-only ledger. Always atomic via `SELECT … FOR UPDATE`.
- Pass `reference=` to dedupe across retries.

## Errors & audit (top-level rules)

- Raise `AppError` subclasses (`NotFound`, `Conflict`, `Forbidden`,
  `Unauthorized`, `ValidationFailed`, `RateLimited`, `PaymentRequired`,
  `InsufficientCredits`). Never bare `HTTPException`.
- Never `try / except Exception: pass`. The global handlers in
  `app/core/error_handlers.py` log at the right severity.
- Every state-changing service path writes an audit entry via
  `audit.record(...)` or `audit.audit_action(...)`. Action names are
  `<resource>.<action>` lowercase snake.
- Webhooks return 400 on signature mismatch, 200 otherwise — never raise
  into the global handler.
- structlog kwargs only — never f-string fields into messages, never log
  secrets.

## Commands

```
make up        # docker compose up
make migrate   # apply alembic migrations
make seed      # default product + plans + admin
make test      # pytest
make lint      # ruff
make typecheck # mypy
```

## Bootstrapping a new product

```bash
curl -X POST http://localhost:8000/api/v1/admin/products \
  -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
  -d '{"name": "ChatBot", "slug": "chatbot"}'
```

Then all `X-Product-Slug: chatbot` calls work. See `docs/multi-product.md`.

## Before opening a PR

- Ran `make lint && make typecheck && make test`.
- New routes guarded by permission deps + product context.
- New product/tenant-scoped queries don't bypass the repository.
- Migration is reversible (or marked forward-only with a reason).
- Audit log entry emitted for every state change.
- No bare `except Exception`; no leaked secrets in logs / audit `diff`.
- At least one cross-product isolation test for any new surface.
