# Product Platform — reusable multi-tenant *multi-product* SaaS scaffold

A drop-in backend layer that hosts **many independent SaaS products** on a
single deployment. Each product is isolated end-to-end: its own tenants,
users, plans, subscriptions, credits, and audit log. Same email or company
can sign up in two products without conflict.

> **Start here:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) is the
> source of truth — HLD + LLD + every documented contract (data model,
> routes, RBAC, jobs / storage APIs that the Electron client uses).
> Every change in this repo updates that doc.

The scaffold provides the boring-but-critical 80% every SaaS, on-prem,
desktop, or mobile app needs:

- **Multi-product** — bootstrap a new product via one admin call; all scoped APIs key off `X-Product-Slug` (or the JWT `pid` claim)
- **Identity** — email/password + JWT (access + refresh) with `pid` claim, Argon2id hashing, password reset, MFA-ready
- **Multi-tenancy** — strict dual `(product_id, tenant_id)` isolation, parent → child tenants with role-gated act-as, B2B + B2C (`Tenant.type`)
- **RBAC + IAM** — `resource:action` permissions (global catalog), per-product system + custom roles, role bindings scoped to a child tenant
- **Plans & Subscriptions** — plan catalog per product, trial → active → past-due → grace → suspended → cancelled lifecycle, upgrade/downgrade with proration hook
- **Billing** — provider-agnostic interface; Stripe driver, mock driver for dev
- **Credits / metered usage** — append-only ledger per tenant, plan-driven monthly allotments, atomic consumption (`SELECT … FOR UPDATE`)
- **Lifecycle ops** — invite, activate / deactivate, soft-delete, audit log of every state change (incl. `acting_from_tenant_id` for act-as)
- **Background jobs** — arq workers for payment reminders, grace-period transitions, credit resets
- **Observability** — structlog JSON, request IDs, `product_id` + `tenant_id` + `user_id` propagated, `/health` and `/ready`
- **DX** — Dockerised, `make up`, autoreload, Alembic, seed, ruff + mypy + pytest

It's an **independent layer**: drop your product modules under `app/products/<name>/`
and consume identity / tenancy / billing / credits via the documented service interfaces.

## Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Web framework | FastAPI | async, OpenAPI baked in, fast |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | mature, async, typed |
| Database | PostgreSQL 16 | JSONB, partial indexes, optional RLS |
| Cache / queue | Redis 7 | arq, rate-limit, idempotency, slug cache |
| Background jobs | arq | Redis-native, ~10× lighter than Celery |
| Migrations | Alembic | the standard |
| Auth | PyJWT + Argon2id (argon2-cffi) | OWASP-recommended |
| Validation | Pydantic v2 | fastest pure-Python validator |
| Billing | Stripe (pluggable) | provider interface in `app/providers/billing` |
| Container | python:3.12-slim multi-stage | ~120 MB runtime image |

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
credits, audit. See `docs/multi-tenancy.md` § "B2B vs B2C".

## Layout

```
app/
  main.py              FastAPI factory, lifespan, middleware
  core/                config, db, redis, security, deps, tenant + product ctx, logging
  models/              SQLAlchemy ORM (Product, Tenant, User, Plan, …)
  schemas/             Pydantic request/response models
  api/v1/              versioned routers (auth, tenants, users, roles, plans,
                         subscriptions, credits, webhooks, admin)
  services/            business logic, transactional boundaries (per product)
  repositories/        DB access — dual (product_id, tenant_id) filter
  providers/billing/   billing-provider abstraction (Stripe, Mock)
  tasks/               arq jobs (reminders, grace, credit resets)
  middleware/          tenant resolver, request ID, rate limit
docs/
  ARCHITECTURE.md      HLD + LLD + Electron API contracts (start here)
  multi-product.md     product isolation
  multi-tenancy.md     tenant isolation + act-as + B2C
  rbac.md              permission model + scope semantics
  billing.md           subscription state machine
  credits.md           ledger model
  deployment.md        production checklist (generic)
  deploy-fly.md        Fly.io + Neon + Upstash runbook
  hosting-and-integration.md   hosting tiers + integration patterns
  postman_collection.json      runnable API collection
migrations/            alembic
tests/                 unit + integration (134 tests, ~17s on Postgres)
.claude/skills/        Claude Code skills for extending the platform
scripts/seed.py        seed default product + plans + admin
```

## Adding a product module on top

1. Read `docs/ARCHITECTURE.md` first.
2. Create the product: `POST /api/v1/admin/products` (with platform-admin token).
3. Optionally create plans for it (with an owner JWT scoped to that product).
4. Drop your product code under `app/products/<your_product>/{models,schemas,api,services}.py`.
5. Register routers in `app/main.py` under the existing tenant-aware deps.
6. If you need metered features, register a credit `feature_key` (see `docs/credits.md`).
7. Use the Claude skill `/add-feature` for the boilerplate.
8. **Update `docs/ARCHITECTURE.md`** for any contract you change (see § "Documentation maintenance contract" in that doc).

## What's intentionally NOT in the scaffold

- A frontend (this is a backend layer).
- Email/SMS sending (interfaces stubbed under `app/providers/notifications.py`; plug SES / Postmark / Twilio).
- Object storage (drop in S3 client where you need it; storage API spec'd in `docs/ARCHITECTURE.md` § 6.3).
- Cross-product SSO (each product registration is independent).
- Search / analytics. Keep this layer boring.

## Operations

- `GET /health` — liveness (always 200 if process up)
- `GET /ready` — readiness (db + redis ping)
- Logs are JSON on stdout, `request_id` + `product_id` + `tenant_id` + `user_id` propagated.

## Docs index

| Doc | When to read it |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **First.** HLD + LLD + every documented contract, including the Electron-facing Jobs / Storage API designs. Source of truth — every code change updates it. |
| [`docs/INTEGRATION.md`](docs/INTEGRATION.md) | **Share this with integrating products.** Self-contained client-side guide; auth flow, headers, endpoint catalogue by UI action, minimal TS + Python client, a `CLAUDE.md` snippet you paste into the consuming product. |
| [`docs/multi-product.md`](docs/multi-product.md) | Product isolation, header / JWT resolution, admin bootstrap |
| [`docs/multi-tenancy.md`](docs/multi-tenancy.md) | Tenant isolation, parent → child act-as, B2B vs B2C |
| [`docs/rbac.md`](docs/rbac.md) | Permission model, scope semantics |
| [`docs/billing.md`](docs/billing.md) | Subscription state machine, upgrade/downgrade rules, provider interface |
| [`docs/credits.md`](docs/credits.md) | Ledger model, atomic consumption pattern |
| [`docs/deployment.md`](docs/deployment.md) | Production checklist (generic) |
| [`docs/deploy-fly.md`](docs/deploy-fly.md) | Concrete Fly.io + Neon + Upstash runbook (generic) |
| [`docs/deploy-plynth.md`](docs/deploy-plynth.md) | Fly runbook tailored to `api.example.com` |
| [`docs/deploy-digitalocean.md`](docs/deploy-digitalocean.md) | **Active** $6/mo DO droplet + Caddy + B2 backups runbook for `api.example.com` |
| [`docs/hosting-and-integration.md`](docs/hosting-and-integration.md) | Hosting tiers + how other products consume this API |
| [`docs/postman_collection.json`](docs/postman_collection.json) | Runnable API collection — import into Postman |
| [`apps/admin-electron/README.md`](apps/admin-electron/README.md) | **Reference Electron client** — desktop admin app for products / tenants / users / plans / subscriptions / credits / audit. Drop-in template for building your own desktop client on top of this platform. |

## License

MIT
