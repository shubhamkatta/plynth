Lets# Product Platform — reusable multi-tenant *multi-product* SaaS scaffold

A drop-in backend layer that hosts **many independent SaaS products** on a
single deployment. Each product is isolated end-to-end: its own tenants,
users, plans, subscriptions, credits, and audit log. Same email or company
can sign up in two products without conflict.

The same scaffold provides the boring-but-critical 80% every SaaS, on-prem
product, desktop, or mobile app needs:

- **Multi-product** — bootstrap a new product via one admin call, then all
  scoped APIs key off `X-Product-Slug` (or the JWT `pid` claim)
- **Identity** — email/password + JWT (access + refresh) with `pid` claim, Argon2id hashing, password reset, MFA-ready
- **Multi-tenancy** — shared-schema with strict dual `(product_id, tenant_id)` isolation, parent → child tenants
- **RBAC + IAM** — fine-grained `resource:action` permissions, per-product system + custom roles, role bindings scoped to tenant or child tenant
- **Plans & Subscriptions** — plan catalog *per product*, trial → active → past-due → grace → suspended → cancelled lifecycle, upgrade/downgrade with proration hook
- **Billing** — provider-agnostic interface; Stripe driver included, mock driver for local dev
- **Credits / metered usage** — append-only ledger per tenant, plan-driven monthly allotments, atomic consumption
- **Lifecycle ops** — invite users, activate/deactivate, soft-delete, audit log of every state change
- **Background jobs** — arq workers for payment reminders, grace-period transitions, credit resets, webhook retries
- **Observability** — structlog JSON logs, request IDs, `product_id` + `tenant_id` + `user_id` propagated, `/health` and `/ready` probes
- **DX** — Dockerised, single `make up`, autoreload, alembic autogenerate, seed script, ruff + mypy + pytest

It's an **independent layer**: drop your product modules under `app/products/<name>/`
and consume identity/tenancy/billing/credits via the documented service interfaces.

## Stack

| Concern         | Choice                                       | Why                                          |
| --------------- | -------------------------------------------- | -------------------------------------------- |
| Web framework   | FastAPI                                      | async, OpenAPI baked in, fast                |
| ORM             | SQLAlchemy 2.0 (async) + asyncpg             | mature, async, typed                         |
| Database        | PostgreSQL 16                                | row-level security, JSONB, partial indexes   |
| Cache / queue   | Redis 7                                      | arq, rate-limit, idempotency, slug cache     |
| Background jobs | arq                                          | Redis-native, ~10× lighter than Celery       |
| Migrations      | Alembic                                      | the standard                                 |
| Auth            | PyJWT + Argon2id (argon2-cffi)               | OWASP-recommended                            |
| Validation      | Pydantic v2                                  | fastest pure-Python validator                |
| Billing         | Stripe (pluggable)                           | provider interface in `app/providers/billing`|
| Container       | python:3.12-slim multi-stage                 | ~120 MB runtime image                        |

## Quick start

```bash
cp .env.example .env
make up                  # bring up db + redis + api + worker
make migrate             # apply schema
make seed                # default product "platform" + plans + admin user
open http://localhost:8000/docs
```

Default seeded admin (change immediately): `admin@example.com` / `ChangeMeNow123!`.
Default product slug: `platform`. Send `X-Product-Slug: platform` on every public
API call (login, register, plan listing); authenticated calls derive the product
from the JWT.

### Spinning up a new product

```bash
curl -X POST http://localhost:8000/api/v1/admin/products \
  -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "ChatBot", "slug": "chatbot"}'

# now register a tenant inside it
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "X-Product-Slug: chatbot" \
  -H "Content-Type: application/json" \
  -d '{"tenant_name": "Acme", "tenant_slug": "acme",
       "email": "owner@acme.example.com", "password": "S3cretPassword!"}'
```

(The platform-admin endpoint seeds system roles automatically. Create
plans for the new product via the plans endpoint — see `docs/multi-product.md`.)

### B2C signup (one user, no company)

For products whose customer is an individual, use `POST /api/v1/auth/register-individual`.
The platform derives a private slug + tenant name; the result is a
`Tenant` with `type=individual` and a single owner user.

```bash
curl -X POST http://localhost:8000/api/v1/auth/register-individual \
  -H "X-Product-Slug: notepad" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "S3cretPassword!",
       "full_name": "Alice Rivers"}'
```

Underneath it's the same `register` flow — same trial subscription,
credits, audit. The user can later invite teammates if the product
grows team features. See `docs/multi-tenancy.md`.

## Layout

```
app/
  main.py              # FastAPI factory, lifespan, middleware
  core/                # config, db, redis, security, deps, tenant+product ctx, logging
  models/              # SQLAlchemy ORM (Product, Tenant, User, Plan, …)
  schemas/             # Pydantic request/response models
  api/v1/              # versioned routers (auth, tenants, users, roles, plans,
                       #   subscriptions, credits, webhooks, admin)
  services/            # business logic, transactional boundaries (per product)
  repositories/        # DB access — dual (product_id, tenant_id) filter
  providers/billing/   # billing-provider abstraction (Stripe, Mock)
  tasks/               # arq jobs (reminders, grace, credit resets)
  middleware/          # tenant resolver, request ID, rate limit
docs/                  # architecture, multi-tenancy, multi-product, rbac,
                       # billing, credits, deployment
migrations/            # alembic
tests/                 # unit + integration (108 tests, ~13s on Postgres)
.claude/skills/        # Claude Code skills for extending the platform
scripts/seed.py        # seed default product + plans + admin
```

## Adding a product module on top

1. Create the product: `POST /api/v1/admin/products` (with platform-admin token).
2. Optionally create plans for it (with an owner JWT scoped to that product).
3. Drop your product code under `app/products/<your_product>/{models,schemas,api,services}.py`.
4. Register routers in `app/main.py` under the existing tenant-aware deps.
5. If you need metered features, register a credit `feature_key` (see `docs/credits.md`).
6. Use the Claude skill `/add-feature` for the boilerplate.

## What's intentionally NOT in the scaffold

- A frontend (this is a backend layer).
- Email/SMS sending (interfaces are stubbed under `app/providers/notifications.py`;
  plug SES / Postmark / Twilio).
- Object storage (drop in S3 client where you need it).
- Cross-product SSO (each product registration is independent).
- Search / analytics. Keep this layer boring.

## Operations

- `GET /health` — liveness (always 200 if process up)
- `GET /ready` — readiness (db + redis ping)
- Logs are JSON on stdout, `request_id` + `product_id` + `tenant_id` + `user_id` propagated.

## Docs

- `docs/architecture.md` — request lifecycle, layering rules, error/audit
- `docs/multi-product.md` — product isolation, header/JWT resolution, admin bootstrap
- `docs/multi-tenancy.md` — tenant resolution, isolation guarantees
- `docs/rbac.md` — permission model, scopes
- `docs/billing.md` — subscription state machine, upgrade/downgrade rules, provider interface
- `docs/credits.md` — ledger model, atomic consumption pattern
- `docs/deployment.md` — production checklist (generic)
- `docs/deploy-fly.md` — concrete Fly.io + Neon + Upstash deploy runbook
- `docs/hosting-and-integration.md` — hosting tiers, integration patterns, parent → child access

## License

MIT
