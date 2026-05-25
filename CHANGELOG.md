# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog v1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.1.0] — 2026-05-25

Initial public release of Plynth — a multi-product, multi-tenant SaaS
backend scaffold with a reference Electron admin client.

### Added

- **Multi-product core** — single deployment hosts many independent SaaS
  products. Every domain row carries `product_id NOT NULL`; public
  endpoints resolve product via `X-Product-Slug` header, authenticated
  endpoints via the JWT `pid` claim, and the two must agree.
- **Multi-tenant core** — every product owns N tenants; every domain row
  carries `tenant_id NOT NULL`; all reads/writes flow through
  `TenantRepository`'s dual `(product_id, tenant_id)` filter. Explicit
  `with bypass_product():` / `with bypass_tenant():` escape hatches for
  reviewed cross-scope code paths.
- **Identity** — email + password registration and login, JWT access
  tokens with refresh-token rotation, Google OAuth sign-in (with
  per-product auto-provisioning toggle), forgot-password and
  change-password flows, and individual / B2C signup via
  `POST /auth/register-individual`.
- **RBAC** — `resource:action` permission codes with `*:*` and
  `users:*` wildcards, per-product system roles seeded on product
  creation, mutating routes guarded by
  `Depends(require_permission(...))`, and direct-child tenant scoping
  via `X-Acting-Tenant-Slug` gated by hierarchy + config + the
  `tenants:act_as_child` permission.
- **Plans + Subscriptions** — provider-agnostic billing with a full
  state machine: `trial → active → past_due → grace → suspended →
  cancelled`.
- **Stripe billing driver** plus a **mock driver** for tests and local
  development, both implementing the `BillingProvider` interface.
- **Credits ledger** — wallet + append-only ledger, atomic updates via
  `SELECT … FOR UPDATE`, retry-safe via `reference=` dedupe.
- **Audit log** — every state-changing service path records an entry
  via `audit.record(...)` / `audit.audit_action(...)`;
  `acting_from_tenant_id` is auto-populated for parent → child actions.
- **Background jobs** — arq worker with Redis broker for async work.
- **Soft-delete with re-invite support** — partial unique indexes
  scoped to `deleted_at IS NULL` let a removed user be re-invited with
  the same email without colliding with the historical row.
- **`Tenant.expires_at` hard cap** — enforced platform-wide; expired
  tenants are blocked at request time.
- **Per-product configuration via JSONB `settings`** — refresh-token
  TTL, Google OAuth auto-provisioning, parent-child act-as toggle, and
  feature flags configurable per product without code changes.
- **Platform-admin god-mode token** — `X-Platform-Admin-Token` unlocks
  the `/api/v1/admin/*` surface for bootstrapping products, tenants,
  and global config.
- **Idempotency keys** — required on mutating billing endpoints to
  guarantee at-most-once semantics across retries.
- **Structured logging** — `structlog` everywhere, kwargs-only API,
  never f-strings into log messages, never secrets.
- **`/health` and `/ready` endpoints** — liveness and readiness probes
  ready for Kubernetes / Fly / Docker healthchecks.
- **Reference Electron admin client** — Electron 32 + React 18 +
  Mantine 7 desktop app under `apps/admin-electron/`, consuming only
  the documented REST API with strict CSP, `contextIsolation: true`,
  `nodeIntegration: false`, `sandbox: true`, and tokens stored via
  `keytar`.
- **Comprehensive documentation** — `docs/ARCHITECTURE.md` (HLD + LLD
  + Electron API contracts) as source of truth, plus focused docs:
  `INTEGRATION.md`, `multi-product.md`, `multi-tenancy.md`, `rbac.md`,
  `billing.md`, `credits.md`, and deploy guides
  (including `corporatethings.com` runbook).
- **173+ tests** covering identity, RBAC, billing state machine,
  credits ledger, audit, cross-product isolation, and child-tenant
  scoping.

### Security

- **`/docs` and `/openapi.json` hidden in production** — schema surface
  is dev-only to avoid leaking internal route catalogue.
- **Partial unique indexes prevent enumeration via soft-delete** —
  attackers cannot probe the existence of historical users.
- **Refresh-token revocation on password change and password reset** —
  forces re-authentication on all devices when credentials rotate.
- **Audit log of every state change** — tamper-evident trail for
  compliance and incident response.
- **Typed `AppError` hierarchy** — `NotFound`, `Conflict`, `Forbidden`,
  `Unauthorized`, `ValidationFailed`, `RateLimited`, `PaymentRequired`,
  `InsufficientCredits`; never bare `HTTPException`, never
  `except Exception: pass`.

[Unreleased]: https://github.com/shubhamkatta/plynth/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/shubhamkatta/plynth/releases/tag/v0.1.0
