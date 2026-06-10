# Architecture — HLD + LLD

> **Source of truth.** Every code change in this repo must consult this
> document, and changes that touch any documented contract (data model,
> service boundary, route, RBAC code, configuration flag, job type,
> storage collection) must update the relevant section in the same PR.
> See `CLAUDE.md` § "Documentation maintenance contract".

Companion documents (focused references — cross-linked throughout):
- `README.md` — quick start + layout
- `docs/INTEGRATION.md` — **shareable guide for integrating products** (give this to other products' Claude Code sessions; includes a copy-paste CLAUDE.md snippet)
- `docs/multi-product.md` — product isolation
- `docs/multi-tenancy.md` — tenant isolation + parent→child act-as + B2C
- `docs/rbac.md` — permission model + scope semantics
- `docs/billing.md` — subscription state machine
- `docs/credits.md` — ledger model
- `docs/deployment.md` — production checklist
- `docs/deploy-fly.md` — Fly.io + Neon + Upstash runbook (generic)
- `docs/deploy-digitalocean.md` — cheapest-prod runbook ($6 droplet + Caddy + B2 backups) on `api.example.com`
- `docs/hosting-and-integration.md` — hosting tiers + platform-owner-facing integration patterns
- `docs/postman_collection.json` — runnable API collection

---

## 1. Overview

This repo is the **platform layer** for a fleet of independent SaaS
products. One deployment serves many products; each product is isolated
end-to-end (its own tenants, users, plans, subscriptions, credits, audit
trail, RBAC). Products consume the platform over HTTPS as one of two
shapes:

| Customer | Tenant model | Sign-up endpoint |
| --- | --- | --- |
| B2B (company / team) | `Tenant.type = company` | `POST /api/v1/auth/register` |
| B2C (individual) | `Tenant.type = individual` (tenant of 1) | `POST /api/v1/auth/register-individual` |

Same primitives underneath — billing, credits, audit, RBAC, parent→child
hierarchy. The `type` marker is purely UX signalling for product clients.

---

## 2. Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Web framework | FastAPI (Python 3.12+) | Async, OpenAPI baked in, Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) + asyncpg | Typed `Mapped[...]`, mature |
| Database | PostgreSQL 16 | JSONB, partial indexes, optional RLS |
| Cache / queue | Redis 7 | arq, rate-limit, slug cache, idempotency |
| Background jobs | arq | Redis-native, ~10× lighter than Celery |
| Migrations | Alembic | The standard |
| Auth | PyJWT + Argon2id | OWASP-recommended |
| Validation | Pydantic v2 | Fastest pure-Python validator |
| Billing | Stripe (pluggable) | Provider interface, mock for dev |
| Container | python:3.12-slim multi-stage | ~120 MB runtime image |

---

## 3. HLD — High-level design

### 3.1 Top-level component diagram

```
                       ┌──────────────────────────────────┐
                       │           CLIENTS                │
                       │  Web · Mobile · Electron · CLI   │
                       └─────────────┬────────────────────┘
                                     │ HTTPS
                                     ▼
   ┌─────────────────────────────────────────────────────────┐
   │                  Cloudflare (DNS + WAF)                 │
   └─────────────────────────────┬───────────────────────────┘
                                 │
                                 ▼
   ┌─────────────────────────────────────────────────────────┐
   │   Fly.io (or VPS) · gunicorn/uvicorn · FastAPI app      │
   │                                                         │
   │   middleware ─→ deps ─→ routers ─→ services ─→ repos    │
   │       │           │         │           │         │     │
   │       ▼           ▼         ▼           ▼         ▼     │
   │  RequestCtx  CurrentUser  /auth      audit/RBAC   ORM   │
   │  RateLimit   RequireProd  /tenants   tenant/sub   FILTER│
   │              act-as       /users     credit       (p,t) │
   │                           ...                           │
   └────────┬────────────────────────────────────────────────┘
            │                              │                  ▲
            ▼                              ▼                  │
   ┌──────────────────┐         ┌──────────────────┐  webhook │
   │  Postgres 16     │         │   Redis 7        │  (Stripe)│
   │  (managed: Neon  │         │  (managed:       │ ─────────┘
   │   or self-host)  │         │   Upstash)       │
   └──────────────────┘         └──────────────────┘
            ▲                              ▲
            │                              │
   ┌────────┴──────────────────────────────┴────────┐
   │           arq worker (always-on)               │
   │   cron: grace sweep · payment reminders        │
   │   jobs: (future) typed handlers for Electron   │
   └────────────────────────────────────────────────┘
```

### 3.2 Core concepts

| Concept | Purpose | Scoped by |
| --- | --- | --- |
| **Product** | One SaaS app on the platform (e.g. "ChatBot", "Notepad") | top of the tree |
| **Tenant** | A customer org (B2B) or single user (B2C `type=individual`) | `product_id` |
| **Tenant tree** | Optional one-level parent→child for workspaces / subsidiaries | `parent_id` |
| **User** | A person who can log in. Belongs to exactly one tenant. | `(product_id, tenant_id)` |
| **Role** | Bundle of permissions; system (owner/admin/member) or custom | `(product_id, tenant_id)` |
| **Permission** | `resource:action` code; **global catalog** | — global — |
| **UserRole** | Binds a user to a role, optionally scoped to a child tenant | `product_id` |
| **Plan** | Catalog entry (price, interval, features). Per-product. | `product_id` |
| **Subscription** | One per tenant; state machine | `(product_id, tenant_id)` |
| **CreditWallet / Ledger** | Metered usage (e.g. `credits.ai_completion`) | `(product_id, tenant_id)` |
| **Invoice** | Payment artifact, from provider webhooks | `(product_id, tenant_id)` |
| **AuditLog** | Every state-changing action | `(product_id, tenant_id)` |

### 3.3 Request lifecycle

1. **ASGI** accepts; `RequestContextMiddleware` binds `request_id` to structlog.
2. **`RateLimitMiddleware`** (Redis sliding window) — fails open on Redis outage.
3. **Route dependency chain**, in order:
   1. `get_db` opens a transactional session.
   2. `resolve_product` reads `X-Product-Slug` (Redis-cached), sets `current_product_id` ContextVar.
   3. For public routes, `RequireProduct` errors if header missing.
   4. For authed routes, `get_current_user`:
      - validates JWT,
      - pulls `pid` + `tid` from claims,
      - verifies header (if present) matches token,
      - optionally consumes `X-Acting-Tenant-Slug` → validates hierarchy + config gates + RBAC → sets `current_tenant_id` to child + `acting_from_tenant_id` to home.
   5. `require_permission("resource:action")` evaluates against the **effective** tenant scope.
4. **Service** runs business logic; **Repository** (`TenantRepository`) auto-applies `WHERE product_id = :pid AND tenant_id = :tid`.
5. **Commit** on clean exit; **rollback** on raise.
6. **Global exception handlers** convert any exception to `{code, message, details}` JSON + structured log at the right severity.

### 3.4 Major data flows

#### Register (B2B)
```
client → POST /auth/register
        + X-Product-Slug

resolve_product → product_id
auth.register
  tenant_svc.create_tenant(type=company)
  User insert
  rbac.ensure_system_roles_for_product
  rbac.assign_role_by_name(owner)
  subscription.start_trial → credit.grant_plan_credits
  audit.record(user.register)
auth.login → JWT (access + refresh)

client ← TokenPair
```

#### Register (B2C / individual)
```
client → POST /auth/register-individual
        + X-Product-Slug
        body: { email, password, full_name? }

auth.register_individual
  slug = "usr-<8 hex>"
  name = full_name | titlecased(email-local-part)
  → register(..., tenant_type=individual)
  retry up to 3× on slug collision

client ← TokenPair
```

#### Login
```
client → POST /auth/login
        + X-Product-Slug
        body: { email, password, tenant_slug? }

auth.login
  SELECT user WHERE email + product_id (+ tenant_slug)
  verify_password (Argon2id)
  on bad password → _audit_in_new_tx(user.login_failed) → 401
  on success     → issue access + refresh tokens
                   record RefreshToken (jti)
                   audit(user.login)

client ← TokenPair
```

#### Subscription purchase
```
client → POST /subscription/purchase
        + Authorization, Idempotency-Key
        body: { plan_code, payment_method_token? }

subscription.purchase
  plan = plan_svc.get_by_code(product_id, plan_code)
  provider.ensure_customer
  provider.create_subscription(idempotency_key=...)
  sub.plan = plan; state = active
  credit.grant_plan_credits(reference=f"period:{sub_id}:{date}")
  audit(subscription.purchase)

client ← SubscriptionResponse
```

#### Consume credits (atomic)
```
client → POST /credits/consume
        body: { feature_key, amount, reference }

credit.consume
  SELECT … FOR UPDATE  (locks the wallet row)
  if reference already in ledger → return (idempotent no-op)
  if balance < amount → raise InsufficientCredits (HTTP 402)
  wallet.balance -= amount
  ledger insert (signed amount, balance_after)
  commit
```

#### Parent → child act-as
```
client → ANY /api/v1/...
        + Authorization, X-Acting-Tenant-Slug

get_current_user
  decode JWT (pid, tid = home)
  _resolve_act_as(target_slug):
    target = SELECT Tenant WHERE slug + product_id
    if target.parent_id != user.tenant_id → 403
    if not product_settings.allow_parent_child_access → 403
    if not parent_tenant_settings.allow_child_access → 403
    if not (act_as_child perm in home OR scoped UserRole on target) → 403
  set_current_tenant(target.id)
  set_acting_from_tenant(user.tenant_id)

→ downstream route uses current_tenant_id() (= child)
→ audit row records (tenant_id=child, acting_from_tenant_id=home)
```

#### Stripe webhook
```
Stripe → POST /webhooks/billing
         + Stripe-Signature

provider.parse_webhook (verifies signature)
  on bad sig → 400 (so Stripe stops retrying)
  on unknown event type → log + 200
  on invoice.payment_failed / payment_succeeded:
    sub = SELECT WHERE provider_subscription_id = ...
    set_current_product(sub.product_id)
    billing.record_invoice(...)
    billing.handle_payment_failed/succeeded
    audit(webhook.payment_*)
  always 200
```

---

## 4. LLD — Low-level design

### 4.1 Module map

```
app/
  main.py                          FastAPI factory · lifespan · middleware
  core/
    config.py                      Settings (pydantic-settings)
    logging.py                     structlog → JSON stdout
    database.py                    async engine · session_scope · get_db
    redis.py                       async redis client + pool
    security.py                    Argon2id · JWT (sub, tid, pid)
    exceptions.py                  AppError taxonomy
    error_handlers.py              Global ASGI exception → JSON envelope
    tenant.py                      ContextVars: product, tenant, acting_from
    dependencies.py                resolve_product · RequireProduct ·
                                   get_current_user · act-as resolver ·
                                   require_permission · platform admin

  models/
    base.py                        Base · UUIDPKMixin · TimestampMixin ·
                                   SoftDeleteMixin · ProductScopedMixin ·
                                   TenantScopedMixin
    product.py                     Product (slug, status, settings)
    tenant.py                      Tenant (type, parent_id, settings)
    user.py                        User · RefreshToken
    role.py                        Role · UserRole (scope_tenant_id)
    permission.py                  Permission (global) · RolePermission
    plan.py                        Plan · PlanFeature
    subscription.py                Subscription (state machine)
    invoice.py                     Invoice (provider-backed)
    credit.py                      CreditWallet · CreditLedger
    audit.py                       AuditLog (acting_from_tenant_id)
    idempotency.py                 IdempotencyKey

  schemas/                         Pydantic request/response DTOs (1 file per resource)

  repositories/
    base.py                        TenantRepository — auto dual filter
                                   (product_id, tenant_id) + scope bypass guards

  services/
    audit.py                       record() + audit_action() context manager
    rbac.py                        scope-aware perms · ensure_system_roles_for_product
    tenant.py                      create_tenant · set_status ·
                                   list_accessible_children
    product.py                     CRUD + slug→id Redis-cached resolver
    user.py                        invite · activate · soft_delete
    auth.py                        register · register_individual · login ·
                                   refresh · logout · change_password
    plan.py                        catalog CRUD
    subscription.py                start_trial · purchase · change_plan ·
                                   cancel · grace · suspend sweep
    credit.py                      grant · consume (FOR UPDATE) · reset_period ·
                                   grant_plan_credits
    billing.py                     record_invoice · handle_payment_(succeeded|failed)

  providers/
    notifications.py               stub: send_email · send_sms
    billing/
      base.py                      BillingProvider ABC + DTOs
      mock.py                      in-memory; default for dev/test
      stripe.py                    real driver (signed webhooks)
      factory.py                   get_billing_provider()

  api/v1/
    router.py                      include_router(...)
    auth.py                        register · register-individual · login ·
                                   refresh · logout · password · me
    tenants.py                     list · create-child · update · activate ·
                                   deactivate · children (act-as discovery)
    users.py                       list · invite · update · activate ·
                                   deactivate · delete (soft)
    roles.py                       list · create · update · assign · permissions
    plans.py                       list (public; needs X-Product-Slug) ·
                                   create · update
    subscriptions.py               get · purchase · change · cancel
    credits.py                     wallets · ledger · consume · grant
    webhooks.py                    /billing (signed)
    admin.py                       /admin/products (platform-admin token)

  middleware/
    request_context.py             request_id + structlog bind
    rate_limit.py                  Redis sliding window; fails open

  tasks/
    worker.py                      arq WorkerSettings + cron registry
    payment_reminders.py           -3/0/+3/+7 day offsets · Redis SETNX dedupe

  (future) jobs/                   typed background job handlers — § 6.2
  (future) storage/                key-value + blob storage — § 6.3

migrations/                        Alembic (env.py, versions/)
scripts/
  seed.py                          default product + plans + admin (idempotent)

tests/
  unit/
  integration/                     134 tests, ~17s on Postgres
```

### 4.2 Database schema (entity reference)

Every domain table has `product_id NOT NULL` except `Permission` (global
catalog). Every tenant-owned table also has `tenant_id NOT NULL`. Naming
convention enforced by `app/models/base.NAMING` so Alembic generates
stable constraint names.

| Table | Key columns | Constraints / notes |
| --- | --- | --- |
| `products` | `slug`, `status`, `settings JSONB` | `uq_products_slug`. `settings.features.allow_parent_child_access` defaults true. |
| `tenants` | `product_id`, `slug`, `parent_id`, `is_root`, `type`, `status`, `settings JSONB` | `uq_tenants_product_slug`. `type ∈ {company, individual}`. `settings.allow_child_access` defaults true. |
| `users` | `product_id`, `tenant_id`, `email`, `password_hash`, `is_active`, `is_verified` | `uq_users_tenant_email`. Argon2id hash. |
| `refresh_tokens` | `product_id`, `user_id`, `jti`, `expires_at`, `revoked_at` | `uq_refresh_tokens_jti`. Revoked on logout / password-change. |
| `permissions` | `code`, `description` | **GLOBAL** (no product_id). `uq_permissions_code`. |
| `roles` | `product_id`, `tenant_id NULL`, `name`, `is_system` | `uq_roles_product_tenant_name`. `tenant_id NULL` = system role (owner / admin / member). |
| `role_permissions` | `role_id`, `permission_id` | `uq_role_permissions_unique`. |
| `user_roles` | `product_id`, `user_id`, `role_id`, `scope_tenant_id NULL` | NULL scope = applies everywhere; non-NULL = applies only when current tenant = X. |
| `plans` | `product_id`, `code`, `price_cents`, `currency`, `interval`, `trial_days`, `is_public`, `provider_refs JSONB` | `uq_plans_product_code`. `provider_refs.stripe = "price_..."` etc. |
| `plan_features` | `plan_id`, `feature_key`, `limit_value`, `credit_amount` | `uq_plan_features_unique`. `credit_amount` granted at each period start. |
| `subscriptions` | `product_id`, `tenant_id`, `plan_id`, `status`, `current_period_*`, `trial_end`, `grace_ends_at`, `provider*` | `uq_subscriptions_tenant`. Status FSM in § 3.4 / `docs/billing.md`. |
| `invoices` | `product_id`, `tenant_id`, `subscription_id`, `provider`, `provider_invoice_id`, `status`, `amount_cents`, `attempt_count` | `uq_invoices_provider_id`. |
| `credit_wallets` | `product_id`, `tenant_id`, `feature_key`, `balance NUMERIC(18,4)`, `period_*` | `uq_credit_wallets_unique`. `SELECT … FOR UPDATE` during consume. |
| `credit_ledger` | `product_id`, `tenant_id`, `wallet_id`, `entry_type`, `amount` (signed), `balance_after`, `reason`, `reference` | Append-only. `reference` dedupes replays. |
| `audit_log` | `product_id`, `tenant_id`, `acting_from_tenant_id NULL`, `actor_user_id`, `action`, `resource_*`, `diff JSONB`, `request_id` | `acting_from_tenant_id` set when acting-as. |
| `idempotency_keys` | `product_id`, `tenant_id`, `key`, `route`, `request_hash`, `response_status`, `response_body JSONB`, `expires_at` | `uq_idempotency_unique`. |

### 4.3 Scope enforcement (the heart of safety)

```python
# app/repositories/base.TenantRepository._stmt
stmt = select(self.model)
if hasattr(self.model, "product_id") and not is_product_bypass():
    stmt = stmt.where(self.model.product_id == current_product_id())
if hasattr(self.model, "tenant_id") and not is_bypass():
    stmt = stmt.where(self.model.tenant_id == current_tenant_id())
```

**Routes filter on `current_tenant_id() or user.tenant_id`** — never
`user.tenant_id` alone — so that act-as switching applies transparently.

**Bypass is explicit:**
```python
with bypass_product():     # cross-product (webhooks, admin, sweeps)
with bypass_tenant():      # cross-tenant within a product (login lookup)
```

Audit trail: `grep -rn bypass_product app/` and `grep -rn bypass_tenant app/`
should each return a small, known set.

### 4.4 RBAC evaluation (scope-aware)

```python
async def list_user_permission_codes(db, user, *, tenant_id=None):
    target_tid = tenant_id if tenant_id is not None else current_tenant_id()
    stmt = (
        select(Permission.code)
        .join(RolePermission).join(Role).join(UserRole)
        .where(UserRole.user_id == user.id)
    )
    if target_tid is not None:
        stmt = stmt.where(
            (UserRole.scope_tenant_id.is_(None))
          | (UserRole.scope_tenant_id == target_tid)
        )
    return set((await db.scalars(stmt)).all())
```

Wildcard matching: `*:*` ⊃ `users:*` ⊃ `users:read`. See `_matches` in
`services/rbac.py`.

### 4.5 Act-as gates (in order, fail-fast)

```
# app/core/dependencies._resolve_act_as
1. target = SELECT Tenant WHERE slug + product_id         → 404 if missing
2. if target.id == user.tenant_id                         → no-op (return home)
3. if target.parent_id != user.tenant_id                  → 403
4. if not product.settings.features.allow_parent_child_access → 403
5. if not home_tenant.settings.allow_child_access         → 403
6. if not (
       user_has_permission(user, "tenants:act_as_child", tenant_id=user.tenant_id)
       or exists(UserRole WHERE user_id + scope_tenant_id = target.id)
   )                                                      → 403
7. return target
```

### 4.6 Background jobs (today)

`arq` worker in `app/tasks/worker.py`. Cron jobs registered in
`WorkerSettings.cron_jobs`:
- `task_check_grace_period` — hourly at `:05`. Moves `GRACE` subs whose
  `grace_ends_at < now()` to `SUSPENDED`.
- `task_send_payment_reminders` — daily 09:00 UTC. Selects open invoices
  at `-3 / 0 / +3 / +7` days of `due_at`, dispatches via
  `app/providers/notifications.send_email`, dedupes per (invoice, offset)
  with Redis `SETNX`.

The worker must be **always-on** (`min_machines_running = 1` on Fly) so
cron fires.

### 4.7 Error handling + audit

Global exception handlers in `app/core/error_handlers.register_handlers`:

| Exception | Status | Log level | `code` in envelope |
| --- | --- | --- | --- |
| `AppError` (subclass) | exc.status_code | warning (<500) / error | `exc.code` |
| `RequestValidationError` | 422 | info | `validation_failed` |
| `StarletteHTTPException` | 4xx/5xx | info / error | derived from `detail` |
| `IntegrityError` | 409 | warning | `conflict` |
| `OperationalError` | 503 | error | `service_unavailable` |
| `SQLAlchemyError` | 500 | exception | `internal_error` |
| catch-all `Exception` | 500 | exception | `internal_error` |

Audit (`app/services/audit.py`):
- `record(...)` — explicit per-action call.
- `audit_action(...)` — async context manager; emits on clean exit,
  logs `action.failed` warning and re-raises on exception (no row).
- Auto-fills `acting_from_tenant_id` from the ContextVar.
- No-op if no product/tenant context (falls back to log only).

### 4.8 Configuration matrix

All settings in `app/core/config.Settings` (pydantic-settings). Loaded
from env vars / `.env`. Important keys:

| Key | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://...?sslmode=require` | — |
| `REDIS_URL` | `redis://` or `rediss://` (TLS) | — |
| `JWT_SECRET` | HS256 signing key, ≥32 bytes | — |
| `JWT_ACCESS_TTL_SECONDS` | access-token lifetime | 900 (15 min) |
| `JWT_REFRESH_TTL_SECONDS` | refresh-token lifetime | 2,592,000 (30 d) |
| `PASSWORD_MIN_LENGTH` | enforced server-side | 12 |
| `BILLING_PROVIDER` | `stripe` \| `mock` | `mock` |
| `STRIPE_API_KEY` / `STRIPE_WEBHOOK_SECRET` | Stripe driver | — |
| `DEFAULT_TRIAL_DAYS` / `GRACE_PERIOD_DAYS` | lifecycle | 14 / 7 |
| `RATE_LIMIT_PER_MINUTE` | per IP / per path | 120 |
| `PLATFORM_ADMIN_TOKEN` | shared secret for `/admin/*` | unset → 403 |
| `CORS_ORIGINS` | list[str] of allowed origins | `[]` |

Per-product config (`Product.settings JSONB`):
- `features.allow_parent_child_access` (bool, default `true`)
- (future) `features.allow_jobs` (bool, default `true`)
- (future) `storage.max_collections`, `storage.max_value_bytes`

Per-tenant config (`Tenant.settings JSONB`):
- `allow_child_access` (bool, default `true`)

---

## 5. Client integration patterns

### 5.1 All clients

Every authenticated call carries:
```
Authorization:        Bearer <accessToken>
X-Product-Slug:       <product>            (optional but recommended)
X-Acting-Tenant-Slug: <child-slug>         (optional; parent→child)
Idempotency-Key:      <uuid>               (on every mutating call)
```

Public calls (no token):
```
X-Product-Slug: <product>                  (required)
```

On 401, refresh the token:
```
POST /api/v1/auth/refresh
body: { refresh_token }
→ new access + refresh pair (old refresh is revoked)
```

CORS: each product's web origin must be in `CORS_ORIGINS`.

### 5.2 Web (browser)

- Store `accessToken` in memory (JS variable / state).
- Store `refreshToken` in an **`HttpOnly; Secure; SameSite=Lax` cookie**
  issued by your own product backend. If the product is a pure SPA
  hitting the platform directly, fall back to `localStorage` and accept
  the XSS risk.
- On 401, hit refresh; on its 401, redirect to login.

### 5.3 Mobile (iOS / Android)

- Store both tokens in the OS secure store: **Keychain** (iOS) or
  **EncryptedSharedPreferences** / Keystore-wrapped (Android).
- Refresh transparently in a network interceptor.

### 5.3.1 Platform-admin god-mode auth

`X-Platform-Admin-Token` is a true super-user across the whole platform —
not just the `/api/v1/admin/*` cross-product endpoints. When a request
carries a valid admin token AND an `X-Product-Slug` header:

- `get_current_user` returns a **transient** `User` instance with
  `is_platform_admin = True`, `product_id` set from the header, and
  `tenant_id` set to that product's root tenant (NIL sentinel if the
  product has no tenants yet — read endpoints return empty lists; write
  endpoints fail naturally).
- `services.rbac.user_has_permission` short-circuits to `True` for the
  flagged user — effective `*:*` permissions on every route.
- `X-Acting-Tenant-Slug` works the same way as for normal users — the
  admin can scope a call into a direct child of the product's root.

Use cases:
- Onboarding tooling that bootstraps a new product end-to-end (create
  product → seed plans → invite first user) without minting a JWT.
- Support workflows where an operator needs read access into any tenant
  without an account inside that tenant.
- The reference Electron admin client (`apps/admin-electron/`) which
  exposes this path via the **Platform Admin** login tab + a product
  picker in the header.

Tests covering this contract: `tests/integration/test_platform_admin_god_mode.py`.

### 5.4 Server-to-server (product backend calling the platform)

Today: use a normal user account dedicated to the integration and rotate
its refresh token via secret manager. **Future**: add `POST /api/v1/api-keys`
that mints long-lived service tokens — small extension.

### 5.5 Electron (the focus of this section)

Electron is a thick client with privileged access to the OS: file I/O,
secure credential storage, native notifications, system tray. The
platform serves it the same APIs as a browser, but Electron-specific
concerns matter:

| Concern | Recommendation |
| --- | --- |
| **Token storage** | `keytar` (npm) → Keychain (macOS) / Credential Manager (Windows) / libsecret (Linux). Never `localStorage` in the renderer. |
| **HTTP from renderer vs main** | Make API calls from the **main** process and IPC results to the renderer. Renderer never sees the refresh token. |
| **CORS** | Not applicable — Electron uses Node `fetch`/`https`, not browser fetch. The platform's `CORS_ORIGINS` doesn't need to list the Electron app. |
| **CSP in renderer** | Restrict to `connect-src https://api.example.com`. |
| **Deep-linking for OAuth** | Register a custom protocol (`yourapp://auth`) for callback. Today the platform uses email+password, but Stripe checkout / SSO would use this. |
| **Background sync** | Use the main-process scheduler (e.g. `node-cron`) for periodic polling; pair with **Jobs API** (§ 6.2) for server-side work. |
| **Offline queue** | Buffer mutations to disk (SQLite/lowdb), retry with the same `Idempotency-Key` on reconnect — the platform's idempotency table dedupes. |
| **Auto-update** | `electron-updater`. Independent of the platform. |
| **Crash reports / telemetry** | Out of scope for the platform. Use Sentry / Bugsnag from the client. |

#### 5.5.1 Reference implementation: `apps/admin-electron/`

A working admin client lives in [`apps/admin-electron/`](https://github.com/shubhamkatta/plynth/tree/main/apps/admin-electron).
It enforces every recommendation in the table above:

- All HTTP runs in the **main process** (`src/main/api/client.ts`); the
  renderer only sees `Result<T>` envelopes via `contextBridge`.
- Tokens (user session + platform admin token) sit in the OS keychain
  via `keytar` (`src/main/api/secrets.ts`).
- 401s trigger a single transparent refresh via `POST /api/v1/auth/refresh`
  before being surfaced to the renderer.
- The renderer is sandboxed with strict CSP, no `nodeIntegration`,
  `contextIsolation: true`, navigation-guard, deny-by-default permissions.
- The IPC surface is enumerated in `src/shared/ipc-channels.ts` — every
  channel and its payload type is auditable in one file.

Use it as the template when building any other Electron client on top of
this platform. See `apps/admin-electron/README.md` for the full
architecture and contribution flow.

**Wired sections** (calls the live API):

- **Products** — `GET / POST /api/v1/admin/products` (platform-admin token).
- **Tenants** — `GET / POST /api/v1/tenants`, `POST /api/v1/tenants/{id}/{activate,deactivate}` (user session, scoped to current product + effective tenant).
- **Users** — `GET / POST /api/v1/users`, `POST /api/v1/users/{id}/{activate,deactivate}`, `DELETE /api/v1/users/{id}` (invite + lifecycle + soft-delete).
- **Roles** — `GET / POST /api/v1/roles`, `PATCH /api/v1/roles/{id}`, `POST /api/v1/roles/assign`, `GET /api/v1/roles/permissions` (per-product role catalogue + global permission codes).
- **Plans** — `GET / POST /api/v1/plans`, `PATCH /api/v1/plans/{code}` (price + currency + interval + trial + features).
- **Subscriptions** — `GET /api/v1/subscriptions` (current tenant's subscription), `POST /api/v1/subscriptions/{purchase,change,cancel}` with proration / at-period-end semantics.
- **Credits** — `GET /api/v1/credits/wallets`, `GET /api/v1/credits/ledger?limit=N`, `POST /api/v1/credits/grant` (manual top-up with idempotency reference).
- **Audit** — `GET /api/v1/credits/ledger` as stand-in until `/api/v1/audit` ships.
- **Dashboard / Settings** — local config + session inspection only.

Every documented section of the platform that exposes admin-relevant
operations is now reachable from this client. New endpoints land here
the same way: extend the IPC channel list → add the main handler →
surface in `BridgeApi` → add the renderer feature folder. See
`apps/admin-electron/README.md` for the contribution checklist.

### 5.6 Official SDKs

For products integrating against this platform, two first-party SDKs
live in `sdks/` and are the recommended way to call the API. Both are
thin, hand-written clients that follow the contracts in `INTEGRATION.md`
exactly — they are not generated from `docs/openapi.json` (kept small
and reviewable).

| SDK | Path | Package | Runtime deps | Sync / Async |
| --- | --- | --- | --- | --- |
| TypeScript / JS | [`sdks/typescript/`](../sdks/typescript/) | `@plynth/sdk` | zero (native `fetch`) | sync only — `Promise`-based; isomorphic Node 20+/browser/Edge |
| Python | [`sdks/python/`](../sdks/python/) | `plynth-sdk` | `httpx` only | both — `PlynthClient` + `AsyncPlynthClient` |

Both SDKs implement the same semantics:

- **Auth resolution order** identical to the manual flow above:
  per-call override → user JWT (from `TokenStore.get()`) → platform-admin
  token + product slug ("god-mode"). Admin-path requests
  (`/api/v1/admin/*`) auto-route through `X-Platform-Admin-Token`.
- **Pluggable token storage** via a `TokenStore` interface — ship
  `MemoryStore` (default), `LocalStorageStore` (browser, opt-in) /
  `FileStore` (Python, mode 0600). Bring your own (keytar, Vault,
  cookies) by implementing the interface.
- **Refresh-once-on-401** — on a 401 to a user-JWT call, the SDK calls
  `/auth/refresh` once, updates the store, and retries the original
  request. Subsequent 401s surface as `PlynthApiError(status=401)`.
- **Idempotency keys** — mutating resource methods (`*.create`,
  `*.update`, `*.consume`, `*.purchase`, …) auto-generate a UUID
  `Idempotency-Key` header. Pass `reference: <uuid>` in the body for
  application-level dedupe (e.g. credits, jobs).
- **Error envelope** — non-2xx responses raise `PlynthApiError` carrying
  `.status`, `.code`, `.message`, `.details`. Transport failures raise
  `PlynthNetworkError`.

Consumers in this repo already use the SDKs:

- [`plynth_cli/`](../plynth_cli/) — Python CLI; `plynth_cli/client.py`
  is a back-compat shim over `plynth_sdk.PlynthClient` with a
  `_CliTokenStore` adapter that round-trips through the existing
  `~/.config/plynth/config.json` layout.
- [`examples/nextjs-starter/`](../examples/nextjs-starter/) —
  `lib/plynth.ts` is a shim over `@plynth/sdk` with a `CookieTokenStore`
  that proxies to HttpOnly cookies via `lib/session.ts`.

The hand-written reference TS + Python snippets in `docs/INTEGRATION.md`
§ 9 still exist and remain authoritative for callers who don't want to
take the SDK as a dependency — they implement the exact same contract.

---

## 6. APIs called by the Electron UI

Authoritative list of every endpoint an Electron client interacts with.
Existing endpoints are linked back to their implementations; designed
endpoints (Jobs, Storage) are not yet implemented and the contract here
*is* the spec — implementers must match it.

### 6.1 Existing endpoints (implemented)

Grouped by typical Electron use case. Full bodies + headers in
`docs/postman_collection.json`.

| UI action | Endpoint | Notes |
| --- | --- | --- |
| Onboard new individual user | `POST /api/v1/auth/register-individual` | Derives slug; returns TokenPair |
| Onboard a team / company | `POST /api/v1/auth/register` | Caller supplies tenant slug |
| Log in | `POST /api/v1/auth/login` | |
| Refresh tokens (transparent) | `POST /api/v1/auth/refresh` | Network-interceptor in main process |
| Log out (current device) | `POST /api/v1/auth/logout` | Pass current refresh token |
| Log out everywhere | `POST /api/v1/auth/logout` | `{ all_sessions: true }` |
| Change password | `POST /api/v1/auth/password` | Revokes all refresh tokens |
| Read current user / permissions | `GET /api/v1/auth/me` | Cache in app state |
| Invite teammate (B2B / family B2C) | `POST /api/v1/users` | Needs `users:write` |
| Manage teammates | `GET/PATCH/DELETE /api/v1/users` + `/users/{id}/activate\|deactivate` | |
| Switch to child workspace | any route + `X-Acting-Tenant-Slug` header | `GET /tenants/children` lists options |
| View / change plan | `GET/POST /api/v1/subscription/*` | `purchase`, `change`, `cancel` |
| Read billing status | `GET /api/v1/subscription` | Display banner if `status ≠ active` |
| Read credit balance | `GET /api/v1/credits/wallets` | Show in tray / status bar |
| Consume credits for a user action | `POST /api/v1/credits/consume` | Pass `reference` for retry-safety |
| List available plans (pricing page) | `GET /api/v1/plans` | Public; needs `X-Product-Slug` only |
| Set / rotate an env var (admin) | `PUT /api/v1/admin/products/{slug}/env/{KEY}` | See § 6.4 |
| List env vars (masked) (admin) | `GET /api/v1/admin/products/{slug}/env` | Previews only; never plaintext |
| Reveal one env var (admin) | `GET /api/v1/admin/products/{slug}/env/{KEY}?reveal=true&reason=...` | High-severity audit row |
| Issue a service token (admin) | `POST /api/v1/admin/products/{slug}/service-tokens` | Returns `pst_…` once |
| Fetch all env vars (product backend) | `GET /api/v1/env`  with `X-Service-Token: pst_…` | Plaintext; never expose token to clients |
| List my components (gate UI) | `GET /api/v1/components` | Returns code/name/is_enabled/source per active component |
| List a user's components (tenant admin) | `GET /api/v1/users/{user_id}/components` | Permission: `components:read` |
| Enable / disable a component for a user | `PUT /api/v1/users/{user_id}/components/{code}` | Permission: `components:override` |
| Clear a per-user override (revert to default) | `DELETE /api/v1/users/{user_id}/components/{code}` | Permission: `components:override` |
| Create / update / delete a component (admin) | `POST/PATCH/DELETE /api/v1/admin/products/{slug}/components/...` | Platform-admin token |
| Server-side Google OAuth exchange | `POST /api/v1/integrations/google/exchange` | `X-Service-Token` with `google:exchange` scope; see § 6.6 |

### 6.2 Jobs API (designed — not implemented)

**Purpose.** The Electron UI captures user actions that take longer than
a request (transcription, export, ML inference, bulk import,
project-wide sync) and enqueues them. The platform persists the job,
arq workers execute it via type-registered handlers, the UI polls (or
streams) for status.

**Status:** designed below; implementer must match this contract.
Tracking: open a task `Implement Jobs API per docs/ARCHITECTURE.md § 6.2`.

#### 6.2.1 Data model (target)

```
table jobs
  id                    UUID PK
  product_id            UUID NOT NULL → products
  tenant_id             UUID NOT NULL → tenants
  type                  STR(64)        e.g. "transcription.audio_to_text"
  status                ENUM           queued | running | done | failed | cancelled
  payload               JSONB          handler-specific input
  result                JSONB | NULL   handler-specific output (when done)
  error                 JSONB | NULL   { code, message } (when failed)
  progress              INT 0..100
  idempotency_key       STR(128) | NULL
  reference             STR(128) | NULL  client-provided correlation id
  callback_url          STR(512) | NULL  webhook on terminal state
  credits_charged       NUMERIC(18,4) | NULL  if the job type maps to a credit feature
  queued_at             TIMESTAMPTZ
  started_at            TIMESTAMPTZ | NULL
  completed_at          TIMESTAMPTZ | NULL
  expires_at            TIMESTAMPTZ    result/row retention
  created_by_user_id    UUID | NULL
  acting_from_tenant_id UUID | NULL

  unique (product_id, tenant_id, type, idempotency_key) WHERE idempotency_key IS NOT NULL
  index  (product_id, tenant_id, status)
```

#### 6.2.2 Endpoints

```
POST /api/v1/jobs                                 [auth, scoped]
  permission: jobs:enqueue
  headers:    Idempotency-Key (recommended)
  body:       {
    "type":          "transcription.audio_to_text",
    "payload":       { ... },          // validated against per-type Pydantic schema
    "callback_url":  "https://...",    // optional
    "reference":     "<client uuid>",  // optional
    "ttl_seconds":   3600              // optional; clamps to product max
  }
  202 → {
    "job_id":   "<uuid>",
    "status":   "queued",
    "poll_url": "/api/v1/jobs/<uuid>"
  }
  Errors:
    402 insufficient_credits     (if type maps to a credit feature and balance < cost)
    409 conflict                 (idempotency replay with a different body)
    422 validation_failed        (unknown type / bad payload shape)

GET /api/v1/jobs/{job_id}                         [auth, scoped]
  permission: jobs:read
  200 → JobResponse  (see § 6.2.3)
  404 if not found in current (product, tenant)

GET /api/v1/jobs                                  [auth, scoped]
  permission: jobs:read
  query: ?status=&type=&reference=&cursor=&limit=50
  200 → { items: [JobResponse], next_cursor }

DELETE /api/v1/jobs/{job_id}                      [auth, scoped]
  permission: jobs:cancel
  204 if cancelled (status was `queued`)
  409 if status is `running` / `done` / `failed` / `cancelled`

GET /api/v1/jobs/{job_id}/stream                  [auth, scoped]   (optional)
  Server-Sent Events; emits a JobResponse on every state/progress change.
  Closes when status is terminal.
```

#### 6.2.3 Response shape

```json
{
  "job_id":           "uuid",
  "type":             "transcription.audio_to_text",
  "status":           "queued | running | done | failed | cancelled",
  "progress":         42,
  "payload":          { ... },
  "result":           { ... } | null,
  "error":            { "code": "...", "message": "..." } | null,
  "reference":        "client-uuid" | null,
  "credits_charged":  "1.00" | null,
  "queued_at":        "2026-05-20T08:01:00Z",
  "started_at":       "2026-05-20T08:01:02Z" | null,
  "completed_at":     "2026-05-20T08:01:45Z" | null,
  "expires_at":       "2026-05-21T08:01:00Z"
}
```

#### 6.2.4 Permissions (new)

Add to `SYSTEM_PERMISSIONS`:
- `jobs:enqueue` — submit jobs (member gets this)
- `jobs:read`    — read own tenant's jobs (member gets this)
- `jobs:cancel`  — cancel a job (member gets this for their own jobs; admin can cancel any)
- `jobs:admin`   — bypass quotas, admin-cancel any (admin/owner)

#### 6.2.5 Handler registry (target)

```python
# app/jobs/__init__.py
from app.jobs.registry import register_job_type

@register_job_type(
    type_code="transcription.audio_to_text",
    payload_schema=AudioToTextPayload,    # pydantic
    result_schema=AudioToTextResult,
    credit_cost=lambda payload: payload.duration_seconds * Decimal("0.01"),
    credit_feature_key="credits.transcription",
)
async def handle_audio_to_text(ctx, payload: AudioToTextPayload) -> AudioToTextResult:
    ...
```

The arq worker picks up unhandled `jobs` rows (or is enqueued by the API
route) and dispatches by `type` to the handler. Failures are caught,
recorded as `failed` with structured error, and audited.

#### 6.2.6 Webhooks back to the client (optional)

If `callback_url` is set, on terminal state the platform POSTs:
```
POST <callback_url>
  X-Platform-Signature: sha256=<hmac>
  body: JobResponse
```
HMAC key is per-product, stored in `Product.settings.webhook_signing_key`.

### 6.3 Storage API (designed — not implemented)

**Purpose.** The Electron UI needs to round-trip per-user data
(documents, project state, preferences, recent files) across devices
without operating its own backend. The platform offers a thin key-value
store + a presigned-URL escape hatch for blobs.

**Status:** designed below; implementer must match this contract.

#### 6.3.1 Data model (target)

```
table storage_kv
  id              UUID PK
  product_id      UUID NOT NULL
  tenant_id       UUID NOT NULL
  collection      STR(64)         e.g. "documents", "preferences"
  key             STR(255)
  value           JSONB           ≤ 1 MB enforced server-side
  version         INT             optimistic-concurrency counter
  expires_at      TIMESTAMPTZ | NULL
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ

  unique (product_id, tenant_id, collection, key)
  index  (product_id, tenant_id, collection, updated_at)   -- for delta sync

table storage_blob_uploads
  id              UUID PK
  product_id      UUID NOT NULL
  tenant_id       UUID NOT NULL
  collection      STR(64)
  key             STR(255)
  content_type    STR(127)
  size_bytes      BIGINT
  status          ENUM             pending | committed | aborted
  storage_url     STR(1024)        s3:// or equivalent
  expires_at      TIMESTAMPTZ
  created_at      TIMESTAMPTZ
```

#### 6.3.2 Endpoints

```
GET    /api/v1/storage/{collection}/{key}         [auth, scoped]
  permission: storage:read
  200 → { value, version, updated_at }
  headers: ETag: W/"<version>"
  404 if not found

PUT    /api/v1/storage/{collection}/{key}         [auth, scoped]
  permission: storage:write
  headers: If-Match: W/"<version>"   (optional optimistic concurrency)
  body:    { value: <json>, ttl_seconds: ... | null }
  200 → { version, updated_at }
  409 if If-Match provided and version mismatched
  413 if value exceeds product limit

DELETE /api/v1/storage/{collection}/{key}         [auth, scoped]
  permission: storage:write
  204

GET    /api/v1/storage/{collection}               [auth, scoped]
  permission: storage:read
  query: ?prefix=...&since=<iso-ts>&cursor=...&limit=100
  200 → { items: [{ key, version, updated_at }], next_cursor }
  // `since` enables delta sync after the Electron app reconnects.

POST   /api/v1/storage/uploads                    [auth, scoped]
  permission: storage:write
  body:  { collection, key, content_type, size_bytes }
  201 → {
    "upload_id":   "uuid",
    "upload_url":  "https://...presigned...",
    "method":      "PUT",
    "expires_at":  "..."
  }

POST   /api/v1/storage/uploads/{upload_id}/commit [auth, scoped]
  body:  {}
  204
  // Marks the blob as available; creates a storage_kv entry pointing at it.
```

#### 6.3.3 Permissions (new)

- `storage:read`
- `storage:write`
- `storage:admin`  (cross-collection management, ttl override)

All three granted to member by default for the user's own tenant.

#### 6.3.4 Quotas

Configurable per product via `Plan.features`:
- `feature_key = storage.kv_max_keys` (limit)
- `feature_key = storage.kv_max_value_bytes` (limit)
- `feature_key = storage.blob_max_bytes_total` (limit, sum across blobs)

Exceeding any returns 413 with `details.feature_key`.

### 6.4 Env-vars vault + service tokens (implemented)

> Source-of-truth contract for the per-product secrets vault. Implemented
> in `app/{core/crypto,models/env_var,models/service_token,services/env_var,services/service_token,api/v1/env_admin,api/v1/env}.py`.
> Schema migration: `scripts/migrate.py` step `0008_env_vars_and_service_tokens`.

#### Purpose

Each product (e.g. `mayva`, `chatbot`) stores its mandatory runtime
config in the platform instead of bundling it inside the product's
package. A product's backend boots, fetches its env vars via API,
hydrates `process.env` (or equivalent), and keeps running. Rotation is
a single API call — no redeploy of the product.

The platform itself consumes this vault for `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` at `/auth/google` time (falls back to platform
`.env` for back-compat).

#### Data model

Two tables, both product-scoped:

```
product_env_vars
  (id, product_id, key, value_encrypted BYTEA, is_secret BOOLEAN,
   description, last_rotated_at, created_at, updated_at)
  UNIQUE (product_id, key)
  key pattern: ^[A-Z][A-Z0-9_]{0,127}$   (conventional ENV_NAME)

product_service_tokens
  (id, product_id, name, token_hash VARCHAR(64), scopes JSONB,
   expires_at, revoked_at, last_used_at, last_used_ip,
   created_at, updated_at)
  UNIQUE (token_hash)
```

#### Encryption at rest

- **Cipher**: AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)
- **Master key**: `ENV_ENCRYPTION_KEY` — 32 bytes, url-safe-b64, no padding. Stored in `/etc/.env`-style secret manager, **never in git**. Generate with
  `python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())"`.
- **Per-row nonce**: 12 bytes from `os.urandom`. Stored as the first 12 bytes of `value_encrypted`.
- **AAD = `<product_uuid>|<key>`** — binds each ciphertext to its row. An attacker with DB write access cannot move a ciphertext between rows; decryption fails authentication.
- **`is_secret=false`** rows skip encryption entirely; the column stores the utf-8 plaintext as bytes. Use for public-safe config (display URLs, feature flags) that benefits from centralised management.
- **Key rotation**: pluggable `KeyProvider` interface in `app/core/crypto.py`. To swap in AWS KMS / Vault, implement `key()` and call `set_key_provider(new)`. No call-site changes.

#### Service token format

```
pst_<32-hex>     ← 44 chars total, shell-safe, no padding
```

- Generated with `secrets.token_hex(16)` (128 bits entropy).
- Stored as **SHA-256 hex of the bearer** — DB leak cannot recover plaintext.
- Plaintext returned ONCE in the `POST /service-tokens` response and forgotten by the platform.
- Scopes (JSONB array of strings) are validated against `ALLOWED_SCOPES` in `app/schemas/service_token.py`. v1 ships `env:read` only.

#### Endpoints

| Action | Endpoint | Auth | Body / Response |
| --- | --- | --- | --- |
| Set or rotate one var | `PUT /api/v1/admin/products/{slug}/env/{KEY}` | platform admin | `{ value, is_secret, description }` → `EnvVarListItem` |
| Patch metadata only | `PATCH /api/v1/admin/products/{slug}/env/{KEY}` | platform admin | `{ is_secret?, description? }` — does NOT rotate `last_rotated_at` |
| List (masked) | `GET /api/v1/admin/products/{slug}/env` | platform admin | List items: secrets show `preview` (`sk_l…cdef`); non-secrets show full `value` |
| Reveal one (audited) | `GET /api/v1/admin/products/{slug}/env/{KEY}?reveal=true&reason=...` | platform admin | Returns plaintext; writes `env.var_revealed` audit row |
| Delete | `DELETE /api/v1/admin/products/{slug}/env/{KEY}` | platform admin | 204 |
| Issue service token | `POST /api/v1/admin/products/{slug}/service-tokens` | platform admin | `{ name, scopes, expires_at? }` → `ServiceTokenIssued` (with `token`) |
| List service tokens | `GET /api/v1/admin/products/{slug}/service-tokens` | platform admin | Metadata only — never the secret |
| Revoke service token | `DELETE /api/v1/admin/products/{slug}/service-tokens/{id}` | platform admin | 204 |
| Fetch env (product runtime) | `GET /api/v1/env`  with `X-Service-Token: pst_…` | service token + `env:read` scope | `{ KEY: plaintext, ... }` |

#### Authentication paths

- Admin endpoints: `require_platform_admin` dep — reuses the platform admin token from `PLATFORM_ADMIN_TOKEN`.
- Product runtime: `require_service_token("env:read")` dep — implements:
  1. Hash the bearer.
  2. Look up by `token_hash`. Miss / revoked / expired → 401 `unauthorized`.
  3. Required scope absent from `scopes` → 403 `forbidden`.
  4. If `X-Product-Slug` is present, it MUST match the token's product (defence in depth) — mismatch → 403.
  5. Stamp `last_used_at` / `last_used_ip`.

#### Audit log

| Action | Severity | When |
| --- | --- | --- |
| `env.var_created` / `env.var_rotated` | info | `set_var` (PUT) |
| `env.var_deleted` | info | DELETE |
| `env.var_revealed` | warning-equiv (operator reason in diff) | `?reveal=true` GET |
| `service_token.issued` | info | POST /service-tokens |
| `service_token.revoked` | info | DELETE /service-tokens/{id} |

The plaintext **never** appears in `audit_log.diff`. Reveal diffs include `reason` and the operator (`actor_user_id`); plaintext stays in the response only.

#### Security posture summary

| Concern | Mitigation |
| --- | --- |
| DB leak | All values encrypted (AES-GCM) with per-row AAD. Token plaintext non-recoverable (SHA-256). |
| Master key leak (env compromise) | Re-encrypt sweep using new key, reissue all service tokens. KMS adoption is the architectural upgrade path. |
| Token leak in logs | `pst_` prefix is greppable. Service tokens never logged by the framework; downstream apps responsible for their own redaction. |
| Cross-product theft | Service token → product mapping is server-side. `X-Product-Slug` mismatch → 403. `aad_for(product_id, key)` rejects ciphertext substitution. |
| Admin abuse (curious operator) | Reveal requires explicit `reason`, writes high-severity audit. List responses redact to first/last 4 chars only. |

#### Server-only key filter

Some env vault keys are used by the platform on the product's behalf
and must never reach a client. They stay in the vault — admin can
read / rotate / reveal them — but are filtered out of the
product-runtime `GET /api/v1/env` response.

Pattern list lives in `app/services/env_var.py`:

```python
SERVER_ONLY_KEY_PATTERNS = (
    re.compile(r"^GOOGLE_(.*_)?CLIENT_SECRET$"),   # used by § 6.6
)
```

The admin list response includes `is_server_only: bool` per row so
operators see at a glance which keys are filtered.

To extend (e.g. when a new platform-mediated integration lands):
add the pattern, ship, no migration needed. Existing vault rows
become server-only on the next list / runtime fetch.

#### Operator playbook

```bash
# 1. One-time on a new droplet: generate + persist the master key.
NEW_KEY=$(python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())")
echo "ENV_ENCRYPTION_KEY=$NEW_KEY" >> /opt/platform/.env
docker compose ... up -d --force-recreate api worker

# 2. Apply migration 0008 (idempotent).
docker compose ... exec api python -m scripts.migrate

# 3. Put a credential into the vault.
curl -X PUT https://api.example.com/api/v1/admin/products/mayva/env/STRIPE_LIVE_KEY \
  -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"value":"sk_live_...","is_secret":true,"description":"Stripe live key"}'

# 4. Issue a service token for the product's backend.
curl -X POST https://api.example.com/api/v1/admin/products/mayva/service-tokens \
  -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"mayva-prod-backend","scopes":["env:read"]}'
# response includes token: "pst_…" — store in the product's secret manager (ops scope).

# 5. Product's backend boots:
curl https://api.example.com/api/v1/env -H "X-Service-Token: pst_…"
# → {"STRIPE_LIVE_KEY":"sk_live_...","GOOGLE_CLIENT_ID":"...",...}
```

### 6.5 Components (implemented)

> Source-of-truth contract for the per-product components system.
> Implemented in `app/{models,schemas,services,api/v1}/component*.py`.
> Schema migration: `scripts/migrate.py` step `0009_product_components`.

#### Purpose

A **component** is a discrete feature module within a product (e.g.
`voice-overlay`, `morning-brief`, `news-triage` for Mayva). The
platform owns the catalog; tenant admins toggle per-user access. The
default is permissive: every user gets every component unless an
explicit per-user override turns it off.

This is the natural shape for product feature-gating that's coarser
than RBAC permissions but finer than plans.

#### Data model

```
product_components
  (id, product_id, code, name, description,
   is_default_enabled BOOLEAN,    -- the bulk knob
   is_active          BOOLEAN,    -- kill switch
   settings JSONB,
   created_at, updated_at)
  UNIQUE (product_id, code)
  code pattern: ^[a-z][a-z0-9-]{0,63}$   (kebab-case slug)

user_component_overrides
  (id, product_id, tenant_id, user_id, component_id,
   is_enabled BOOLEAN, reason, set_by_user_id, set_at,
   created_at, updated_at)
  UNIQUE (user_id, component_id)
```

#### Effective access

For a given (user, component):

1. Look up the override row keyed by (user_id, component_id).
2. **If present** → `override.is_enabled` wins.
3. **If absent** → `component.is_default_enabled` is the answer.
4. Inactive components (`is_active = false`) are uniformly hidden
   from listings and access checks return False.

Helpers in `app/services/component.py`:
- `user_effective_components(user)` → `[(component, is_enabled, source, reason)]`
- `user_has_component_access(user, code) -> bool` for single-call gates.

#### Endpoints

| Action | Endpoint | Auth | Notes |
| --- | --- | --- | --- |
| List (admin, incl. inactive) | `GET /admin/products/{slug}/components` | platform admin | |
| Create | `POST /admin/products/{slug}/components` | platform admin | `code` immutable after create |
| Update | `PATCH /admin/products/{slug}/components/{code}` | platform admin | name / description / `is_default_enabled` / `is_active` / `settings` |
| Delete | `DELETE /admin/products/{slug}/components/{code}` | platform admin | Cascades to override rows |
| List (user view, active only) | `GET /components` | user JWT | `[{code, name, is_enabled, source, description, reason?}]` |
| List for one user | `GET /users/{user_id}/components` | RBAC `components:read` | Target user must be in same tenant |
| Set override | `PUT /users/{user_id}/components/{code}` | RBAC `components:override` | Idempotent on (user_id, component_id) |
| Clear override | `DELETE /users/{user_id}/components/{code}` | RBAC `components:override` | Reverts to default |

Plus a convenience embed in `GET /auth/me`:

```json
{
  ...,
  "components": {"voice-overlay": true, "alpha-feature": false}
}
```

#### Permissions

Two RBAC codes (auto-seeded; no extra migration step):

- `components:read` — list components + see per-user effective access.
  Owner / admin / member all get this.
- `components:override` — enable / disable for a specific user in the
  current tenant. Owner / admin only.

#### Audit

Every state change writes one of:
`component.created`, `component.updated`, `component.deleted`,
`component.override_created`, `component.override_updated`,
`component.override_cleared`.

The component's `code` and target `user_id` go into `diff`; component
`settings` does NOT.

#### Common patterns

```python
# Product-runtime gate.
from app.services.component import user_has_component_access
if not await user_has_component_access(db, user=user, code="voice-overlay"):
    raise Forbidden("voice-overlay not enabled for this user")
```

```typescript
// Client: render conditionally on /me.components — no second round-trip.
const me = await client.auth.me();
if (me.components["voice-overlay"]) renderVoiceOverlay();
```

### 6.6 Integrations: Google OAuth exchange (implemented)

> Source-of-truth contract for the platform-mediated OAuth token swap.
> Implemented in `app/services/google_oauth.py` +
> `app/api/v1/integrations.py`. No schema migration — reuses
> `product_env_vars` for the client_secret lookup.

#### Purpose

Eliminate `client_secret` leakage through shipped desktop products.
Clients send the PKCE-protected `code` (or stored `refresh_token`)
plus the public `client_id` to the platform; the platform finds the
matching secret in the product's env vault, swaps with Google, and
returns Google's response verbatim. Tokens are never persisted by
the platform.

Endpoint: `POST /api/v1/integrations/google/exchange`. Auth:
`X-Service-Token` with the new `google:exchange` scope.

#### Secret lookup convention

The env vault may hold multiple Google OAuth client pairs under the
naming convention:

```
GOOGLE_<group>_CLIENT_ID         ↔ GOOGLE_<group>_CLIENT_SECRET
```

Default (omit `<group>`) is `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
A second client for a different scope tier (e.g. Gmail access on a
restricted client) uses `GOOGLE_GMAIL_CLIENT_ID` /
`GOOGLE_GMAIL_CLIENT_SECRET`.

The service iterates the product's `GOOGLE_*_CLIENT_ID` vault rows,
decrypts each, and matches the request's `client_id` against the
plaintext value. The matching row's key with `_CLIENT_ID` replaced
by `_CLIENT_SECRET` is the secret used for the swap. Unknown
`client_id` → `422 validation_failed`.

This iteration is intentional rather than encoding `client_id` into
the env key name — keeps operator-facing keys short and human-readable.

#### Request / response shape

See `app/schemas/integrations.py`. Two grant types
(`authorization_code`, `refresh_token`) discriminated by Pydantic.
`code_verifier` is required (43-128 chars) on `authorization_code` —
PKCE is mandatory. Response is a verbatim pass-through of Google's
token body (`refresh_token` absent on most refresh-grant responses;
do not synthesize).

#### Error mapping

| Failure | Platform envelope |
| --- | --- |
| Missing / invalid service token | `401 unauthorized` |
| Token lacks `google:exchange` scope | `403 forbidden` |
| `X-Product-Slug` mismatches token's product | `403 forbidden` |
| Pydantic body validation (`code_verifier` missing etc.) | `422 validation_failed` |
| Unknown `client_id` for this product | `422 validation_failed` |
| Google 4xx (e.g. `invalid_grant` on revoked refresh) | `401 unauthorized`; `message = "google: <error>"`, `details.google_error` |
| Google 5xx / network failure | `503 service_unavailable` |

#### Privacy & logging

- The platform NEVER persists `code`, `code_verifier`,
  `refresh_token`, `access_token`, or the resolved `client_secret`.
- Logs include `product_id`, `client_id_tail` (last 16 chars),
  `grant_type`, outcome, and `google_status` only.

#### Scope addition

`google:exchange` is a new entry in
`app/schemas/service_token.py:ALLOWED_SCOPES`. Existing tokens that
only carry `env:read` must be re-issued (or have their `scopes`
JSONB field updated) to call this endpoint.

#### Two-step cutover for an existing product

1. Deploy this endpoint. While `GOOGLE_CLIENT_SECRET` is still in the
   product's `/env` response, clients keep exchanging directly with
   Google (no behaviour change).
2. As a reversible vault operation, remove the `*_CLIENT_SECRET` rows
   from the product's vault (or mark them so `/env` filters them
   out). Clients fall back to this endpoint on next boot. Revert by
   re-PUT-ing the secret if any error spike appears.

`GOOGLE_*_CLIENT_ID` rows MUST remain — clients need the public id
for the consent URL.

---

## 7. Cross-cutting concerns

### 7.1 Security

- Passwords: Argon2id via `argon2-cffi`. OWASP-recommended.
- JWT: HS256 with `JWT_SECRET ≥ 32 bytes`. Tokens carry `pid` + `tid`.
- Refresh tokens: server-tracked (`refresh_tokens` table) → revocable on logout / password change.
- Idempotency: `Idempotency-Key` header on every mutating billing/credit/jobs call. Persisted in `idempotency_keys`.
- Webhook signature: provider-verified (`provider.parse_webhook`); failures return **400** so providers stop retrying.
- Rate limit: Redis sliding window per IP + path; **fails open** on Redis outage (log warning).
- CORS: explicit allow-list via `CORS_ORIGINS`; never `*` with credentials.
- Audit: every state change writes an `audit_log` row, including the actor's `acting_from_tenant_id` on parent→child operations.

### 7.2 Observability

- **Logs**: structlog → JSON on stdout. `request_id`, `product_id`, `tenant_id`, `user_id` propagated into every line of a request via `structlog.contextvars`.
- **Health**: `GET /health` (always 200 if process up) · `GET /ready` (DB + Redis ping).
- **Tracing**: not wired; add `opentelemetry-instrumentation-fastapi` + `…-sqlalchemy` when needed.
- **Metrics**: not wired; add `prometheus-fastapi-instrumentator` for `/metrics`.

### 7.3 Performance & scaling

- One transaction per HTTP request (open in `get_db`, commit on clean exit).
- `selectinload` for collections that the route reads — never `lazy='select'` followed by access (will MissingGreenlet in async).
- Credit consume serialises on the wallet row (`SELECT … FOR UPDATE`).
- arq worker is always-on; API can scale-to-zero.
- DB connection pool sized via `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`.

### 7.4 Testing

- `tests/conftest.py` seeds two products (`producta`, `productb`) per session, truncates tenant data per test, preserves the platform catalog.
- 134 tests, ~17s against real Postgres + Redis (Docker).
- See `.claude/skills/testing/SKILL.md` for conventions.

---

## 8. Documentation maintenance contract

> **Every code change in this repo updates this document if it touches
> any documented contract.** This is non-negotiable.

**Touchpoints** (if your change affects ANY of these, edit
`ARCHITECTURE.md` AND the relevant focused doc, in the same PR):

| Change | Update in `ARCHITECTURE.md` | Also update |
| --- | --- | --- |
| New / removed / changed DB column | § 4.2 (schema reference) | — |
| New / removed / changed model | § 4.1 (module map) + § 4.2 (schema) | — |
| New / removed / changed route | § 6.1 (existing endpoints) | `docs/postman_collection.json` |
| New permission code | § 4.4 (RBAC) + § 6.2/6.3 if jobs/storage | `docs/rbac.md` |
| New / changed configuration key | § 4.8 (configuration matrix) | `.env.example` |
| New / changed external integration (Stripe, Email) | § 2 (stack) + § 3.4 (flows) | — |
| New / changed background job | § 4.6 (jobs today) | — |
| Any change visible to integrating products (new endpoint, changed shape, new header, new error code) | § 6.1 / 6.2 / 6.3 here | `docs/INTEGRATION.md` (mirror to keep client-facing doc honest) **and** `sdks/typescript/` + `sdks/python/` (add the resource method on both, with tests) |
| SDK behavior change (auth resolution, header semantics, refresh / idempotency / error envelope) | § 5.6 (Official SDKs) | both `sdks/*/README.md` |
| Env-vars vault — new endpoint, new audit action, new scope, key-provider change | § 6.4 + § 6.1 endpoint table | `docs/INTEGRATION.md` § 9.3, both `sdks/*/README.md` |
| Components — new endpoint, new audit action, new permission code, schema change | § 6.5 + § 6.1 endpoint table | `docs/INTEGRATION.md` § 9.4, both `sdks/*/README.md` |
| Integrations / Google OAuth exchange — new endpoint, new scope, new error mapping | § 6.6 + § 6.1 endpoint table | `docs/INTEGRATION.md` § 9.5 |
| Jobs API change | § 6.2 | implementer must keep contract truthful |
| Storage API change | § 6.3 | implementer must keep contract truthful |
| Multi-product behavior | § 3.2, § 4.3 | `docs/multi-product.md` |
| Multi-tenancy / act-as behavior | § 3.4, § 4.5 | `docs/multi-tenancy.md` |
| Billing state machine | § 3.4, § 4.6 | `docs/billing.md` |
| Credits semantics | § 3.4, § 4.6 | `docs/credits.md` |
| Deployment recipe / stack | § 2, § 3.1 | `docs/deploy-fly.md`, `docs/deployment.md` |

**Workflow:**
1. **Read** this doc before designing the change.
2. **Implement.**
3. **Update** the affected sections of this doc (and the focused doc, if any) in the same commit/PR as the code change.
4. **Tests** must pass before merging.

If a designed-but-not-implemented contract (Jobs API § 6.2, Storage API
§ 6.3) is later implemented, mark it **"implemented"** at the top of that
section and link the implementing PR. If implementation deviates from
the contract, **update the contract here first** then implement; never
ship divergence silently.

---

## 9. Glossary

| Term | Meaning |
| --- | --- |
| **Product** | A SaaS application hosted on this platform (e.g. ChatBot, Notepad) |
| **Tenant** | A customer org (B2B) or single user (B2C). Billing + audit boundary. |
| **Home tenant** | The tenant a user was created in (their JWT `tid`) |
| **Effective tenant** | `current_tenant_id()`; equals home unless acting-as |
| **Act-as** | Parent-tenant user scoping a request to a child via `X-Acting-Tenant-Slug` |
| **Permission** | `resource:action` code (global catalog) |
| **System role** | `owner`/`admin`/`member`, seeded per product |
| **Scoped binding** | `UserRole.scope_tenant_id = X` — role applies only when current scope = X |
| **Idempotency key** | Client-supplied uuid in `Idempotency-Key` header; replays return the first response |
| **Reference** | Application-supplied dedupe key on credit ledger / job submissions |
| **Bypass** | `bypass_product()` / `bypass_tenant()` — explicit escape from repository auto-filter |


---

## 10. API versioning + deprecation policy

All HTTP routes are namespaced under `/api/v1/...`. The platform follows
semver-ish discipline for that surface:

- **Pre-1.0 (now):** the contract may move between releases. Pin to a
  commit SHA in production; read the `CHANGELOG.md` before bumping.
- **At v1.0:** the `/api/v1` surface freezes. Breaking changes require
  a new prefix (`/api/v2`); old prefixes get a deprecation window of
  at least **6 months** with `Sunset` and `Deprecation` response
  headers per [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html)
  + [RFC 8594](https://www.rfc-editor.org/rfc/rfc8594.html).
- **Within a minor version**, additive changes only: new endpoints,
  new optional request fields, new response fields. Removing a field,
  tightening a validation rule, or changing a status code is a
  breaking change.
- **Error-envelope shape** (`{code, message, details, status}`) is
  considered part of the public contract. New `code` values are
  additive — clients should treat unknown codes as the catch-all
  family they match (e.g. `*_failed` → validation, `*_not_found` →
  404).
- **JWT claims** (`sub`, `pid`, `tid`, `typ`, `iat`, `exp`, `jti`)
  are stable; new claims may be added but never removed without a
  major bump.
- **Per-product `settings` JSONB keys** (e.g.
  `settings.auth.refresh_ttl_days`, `settings.features.*`) follow the
  same additive policy. Renamed keys are dual-read for at least one
  minor version.

### What counts as breaking

A change is breaking — and requires a new major prefix or a
documented deprecation — if it can make a previously-working
client request newly fail, or interpret a previously-meaningful
response differently. In practice that means:

- Removing or renaming a route, request field, response field, or
  error `code`.
- Tightening a field's validation (narrower regex, smaller max).
- Changing a default value or implicit behaviour.
- Changing an HTTP status code (200 → 204, 422 → 409, etc.).
- Changing a JWT claim's type or removing a claim.

What is **not** breaking:
- Adding a new route, optional request field, optional response field,
  or new error `code` to the global catalog.
- Making a response field optional (clients should handle absent fields).
- Loosening validation.

### Discovering the contract

- `docs/openapi.json` — committed copy of the OpenAPI 3.1 schema, regenerated by `make openapi` and bumped per release.
- `docs/INTEGRATION.md` — narrative consumer guide.
- `docs/postman_collection.json` — runnable API calls.

### Reporting accidental breakage

If you find a release that changed the `/api/v1` surface without an
intentional deprecation, open a `bug` issue with the old + new request
or response shape. Pre-1.0 we'll fix forward; post-1.0 we'll revert
and re-release.
