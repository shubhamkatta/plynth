# Reddit launch posts pack

> Stagger across 2-3 days. NEVER post identical text to multiple subs — Reddit's automod flags cross-posts even with different titles. Each post below is rewritten for the sub's audience.
>
> Don't post Show HN day. Wait 2-4 days after HN to layer the Reddit traffic.
>
> No emoji in titles (most subs strip or penalize). Plain text wins.

## Pre-flight

- [ ] Account has positive karma + age in the target sub (lurk-engage for 1-2 weeks if new)
- [ ] Read each sub's pinned rules + recent removed-posts list (modlog if public)
- [ ] Have screenshots ready (they boost engagement on text posts too — Reddit allows inline images)
- [ ] Reply to every comment within 1 hour for the first 4 hours

---

## 1. r/Python

**Title**: `[Project] Plynth — drop-in multi-product SaaS backend (FastAPI, async SQLAlchemy, MIT)`

**Body**:

Plynth is an MIT-licensed FastAPI + async SQLAlchemy backend that lets one deployment host many independent SaaS products — each with its own tenants, users, plans, subscriptions, credits, audit log — fully isolated end-to-end. I built it because I kept rebuilding the same boring plumbing every time I started a new product, and I wanted the abstraction to be `(product_id, tenant_id)` keyed at the data layer instead of bolted on at the route layer.

Repo: `https://github.com/shubhamkatta/plynth` — happy to talk about any of the pieces below.

**Isolation primitive (the part I'd want code-reviewed first).** Every domain table inherits `ProductScopedMixin` and `TenantScopedMixin`, and every read/write goes through a `TenantRepository` that auto-injects the dual filter from a request-scoped `ContextVar`. From `app/repositories/base.py`:

```python
def _stmt(self) -> Select[Any]:
    stmt: Select[Any] = select(self.model)
    if hasattr(self.model, "product_id") and not is_product_bypass():
        pid = current_product_id()
        if pid is None:
            raise RuntimeError(
                f"{self.model.__name__} repository used without an active "
                "product context. Set one via the product dependency or "
                "wrap in bypass_product()."
            )
        stmt = stmt.where(self.model.product_id == pid)
    if hasattr(self.model, "tenant_id") and not is_bypass():
        tid = current_tenant_id()
        if tid is None:
            raise RuntimeError(...)
        stmt = stmt.where(self.model.tenant_id == tid)
    return stmt
```

`add()` symmetrically stamps `product_id` and `tenant_id` from context, and **raises** if you pre-set them to something that disagrees. The point: there is no path through services that touches a cross-product row by accident — only by explicit, grep-able `with bypass_product():` or `with bypass_tenant():` blocks (used for slug resolution, system role seeding, webhooks, the platform admin token). Every bypass is reviewable line by line.

**RBAC wildcard match.** Permissions are `resource:action` codes from a global catalogue (`*:*`, `users:*` allowed). The matcher is intentionally three lines (from `app/services/rbac.py`):

```python
def _matches(granted: str, required: str) -> bool:
    """`*` matches any single segment; full wildcard `*:*` matches everything."""
    g_res, g_act = granted.split(":", 1)
    r_res, r_act = required.split(":", 1)
    return (g_res in ("*", r_res)) and (g_act in ("*", r_act))
```

Roles are per-product (system roles seeded on `POST /admin/products`), bindings can be scoped to a child tenant via `UserRole.scope_tenant_id`, and every mutating route is guarded with `Depends(require_permission("users:write"))`.

**Auth dep chain.** A request to an authenticated route resolves like this:

1. `Depends(get_db)` → `AsyncSession` (one txn per request)
2. `Depends(resolve_product)` → looks up `X-Product-Slug` via Redis-cached slug→id, raises `ValidationFailed` on unknown, `Forbidden` on suspended, sets a `ContextVar`.
3. `Depends(get_current_user)` → decodes the JWT, **asserts `pid` claim equals header-resolved product** (the two must agree, or it's `Unauthorized`), pulls the user under `bypass_product()` + `bypass_tenant()`, then re-pins the tenant context to the user's home tenant (or to `X-Acting-Tenant-Slug` if act-as is in play).
4. `Depends(require_permission("..."))` → calls `_matches` against the user's permission set in the **current** tenant scope (act-as flips this).

Per-product config lives in JSONB on `Product.settings`. Example, refresh-token TTL is per-product with platform fallback:

```python
days = (product.settings or {}).get("auth", {}).get("refresh_ttl_days")
if isinstance(days, int) and 1 <= days <= 365:
    return days * 86400
return settings.jwt_refresh_ttl_seconds
```

**Errors and audit.** Services raise typed `AppError` subclasses (`NotFound`, `Conflict`, `Forbidden`, `Unauthorized`, `ValidationFailed`, `RateLimited`, `PaymentRequired`, `InsufficientCredits`). A single global handler turns them into a `{code, message, details}` envelope and logs at the right severity (4xx → `warning`, 5xx → `error`). Every state-changing path writes an audit row with `request_id`, `product_id`, `tenant_id`, `user_id`, and `acting_from_tenant_id` propagated through structlog.

**Tooling and coverage.** Python 3.12, mypy strict on `app/`, ruff, pytest with 200+ tests (unit + integration against a real Postgres in Docker), codecov, GitHub Actions. The whole suite runs in ~17s.

**Feedback I'd love.** (a) The `ContextVar` pattern for tenancy — anyone been burned by it in async code I should worry about? (b) `_matches` is dead simple but I expect someone here has a better permission-evaluation idea. (c) The "header + JWT must agree" check — overkill or right call?

Repo, docs, deploy runbooks: `https://github.com/shubhamkatta/plynth` · docs at `https://shubhamkatta.github.io/plynth`. MIT. PRs and issues very welcome.

---

## 2. r/FastAPI

**Title**: `Built a multi-tenant multi-product SaaS scaffold on FastAPI — looking for design feedback`

**Body**:

I have been building Plynth (`github.com/shubhamkatta/plynth`, MIT) — a FastAPI backend designed to host many independent SaaS products on one deployment, with strict `(product_id, tenant_id)` isolation. It is heavily FastAPI-flavored and I'd like a sanity check from this sub on a few of the patterns before more people start forking it.

**The dependency chain.** Every authenticated route ends up looking like this:

```python
@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    product_id: RequireProduct,                       # resolves X-Product-Slug
    current_user: Annotated[User, Depends(get_current_user)],
    _: None = Depends(require_permission("users:write")),
) -> UserOut:
    return await users_svc.create(db, payload, actor=current_user)
```

`RequireProduct` is just `Annotated[UUID, Depends(require_product)]` — a tiny convenience that fails the request with `ValidationFailed` if no `X-Product-Slug` was sent. `resolve_product` itself sets a `ContextVar` (`current_product_id`) that the repository layer reads transparently — there is no "pass tenant_id everywhere" plumbing in services or queries.

`get_current_user` decodes the JWT, then **asserts the `pid` claim equals the header-resolved product**. If they disagree it raises `Unauthorized`. I think this is the right default but it's a friction point if anyone wants to share a token across products — would love opinions.

**Typed error envelope via one global handler.** Services raise `AppError` subclasses (`NotFound`, `Conflict`, `Forbidden`, `Unauthorized`, `ValidationFailed`, `RateLimited`, `PaymentRequired`, `InsufficientCredits`). The handler is the only place that knows about HTTP:

```python
@app.exception_handler(AppError)
async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    level = log.warning if exc.status_code < 500 else log.error
    level("app_error", code=exc.code, status=exc.status_code, **_ctx(request))
    return JSONResponse(
        _envelope(exc.code, exc.message, exc.details),
        status_code=exc.status_code,
    )
```

Routers never construct `HTTPException` themselves. The downstream Electron admin client gets a consistent `{code, message, details}` shape and wraps it in a `Result<T, ApiError>` envelope in TypeScript — the renderer never sees a raw throw, which makes UI error handling pleasant.

**Per-product config at issue-token time.** Refresh TTL is on `Product.settings` JSONB, looked up when minting the refresh token:

```python
async def _refresh_ttl_seconds(db: AsyncSession, product_id: UUID) -> int:
    with bypass_product(), bypass_tenant():
        product = await db.get(Product, product_id)
    if product is not None:
        days = (product.settings or {}).get("auth", {}).get("refresh_ttl_days")
        if isinstance(days, int) and 1 <= days <= 365:
            return days * 86400
    return settings.jwt_refresh_ttl_seconds
```

Same pattern (`Product.settings.features.*`) gates Google auto-provisioning, parent→child tenant act-as, and a few other knobs. Means one deployment can serve a strict-compliance B2B product and a lenient B2C product side by side.

**Stack.** FastAPI · SQLAlchemy 2.0 async + asyncpg · Postgres 16 · Redis 7 · arq workers · Alembic · Pydantic v2 · PyJWT + Argon2id · pytest + mypy strict on `app/` + ruff. 200+ tests, runs in ~17s on a real Postgres in Docker.

**Open questions for the sub:**

1. **`ContextVar` for tenant scope** — has anyone hit footguns with this in production async FastAPI? Background tasks I solve with `session_scope()` that re-pins context; anywhere else I should worry?
2. **The header + JWT consistency check** — is rejecting the request the right default, or should I just trust the JWT and ignore the header on authenticated routes?
3. **Repository auto-injection vs explicit-args** — I went with implicit (via ContextVar). Some folks prefer passing `tenant_id` explicitly to every query for grep-ability. Anyone done both and have a preference at scale?

Code: `https://github.com/shubhamkatta/plynth`. Docs: `https://shubhamkatta.github.io/plynth`. Roast freely — I'd rather hear it now than after fifty forks.

---

## 3. r/SaaS

**Title**: `I open-sourced the backend I wish I had every time I started a new SaaS`

**Body**:

Every time I started a new SaaS, I spent the first six months rebuilding the exact same plumbing: signup and login, password reset, OAuth, multi-tenancy with strict isolation, roles and permissions, plans and billing, the trial/active/past_due/grace/cancelled state machine, metered credits, audit logs, deploy. Six months. Every time. None of it was the actual product.

So I built it once, properly, and open-sourced it. It is called **Plynth**. MIT licensed. Fork it, drop your product code on top, ship in a week instead of six months. Demo + repo in the first comment.

**What it is.** A backend layer for SaaS founders. It is not a frontend, not a no-code tool, not a hosted service. It is the boring identity-billing-audit guts of a B2B or B2C app, packaged as a reusable foundation. You bring the actual product idea and the UI.

**The piece nobody else does — multi-product.** Most SaaS infra (Supabase, Nhost, the usual scaffold repos) assumes one product per deployment. If you are like me and you build multiple products, that means duplicate billing accounts, duplicate auth, duplicate audit, duplicate ops, duplicate everything. Plynth treats "product" as a first-class concept. One deployment, one Postgres, one worker pool can host an internal tool plus a B2C app plus a B2B platform, each with its own tenants, users, plans, subscriptions, and credit wallets, fully isolated. Adding a new product is one API call. Same email can sign up across products with no conflict.

**What's in the box.** The founder-relevant version, not the engineering version:

- Email + password signup and login, password reset, Google OAuth, JWT sessions with revocation.
- Multi-tenant from day one. B2B (companies with users) and B2C (one user, no company) in the same model. Parent-child tenant hierarchy for enterprise customers.
- Roles and permissions out of the box. Owner / admin / member system roles, build your own custom ones per product.
- Plans, subscriptions, the full lifecycle state machine (trial → active → past_due → grace → suspended → cancelled), upgrade and downgrade with proration.
- Stripe driver included, plus a mock driver for local dev so you don't need a Stripe account to develop. The interface is pluggable — swap in Paddle or LemonSqueezy without touching your routes.
- Metered credits with an append-only ledger, monthly allotments from the plan, atomic consumption that is safe under retries.
- Audit log for every state change. When something goes wrong (and it will) you can answer "who did what when" instantly.
- Background jobs for the boring stuff: payment reminders, grace-period transitions, monthly credit resets.
- A reference Electron desktop admin app — manage every product, tenant, user, subscription, credit balance, and audit row from one window. Useful for support workflows.

**What's NOT in it (on purpose).** No frontend for your actual product — bring whatever you want (Next.js, mobile, native). No email sender — interfaces are stubbed; plug in Postmark, SES, or Resend in 20 lines. No object storage — bring an S3 client. No analytics — bolt it on outside.

**Where this saves you time vs the obvious alternatives.** Supabase is faster if you are shipping one product and want hosted + a UI library bundled in. Plynth wins if you want to ship multiple products on shared infra, want to own your identity-billing-audit stack end to end, want to self-host on a $6 droplet, or prefer Python. Vs DIY: you don't write any of this. Vs Django + django-tenants: async-native, multi-product as a first-class concept, includes the billing and credits machinery Django assumes you'll bolt on.

**My honest ask.** I am curious what other founders here are using for this layer. What did you build, what did you buy, what did you regret? If anyone wants to try Plynth on a new project I will personally help you wire it up — drop a comment or DM.

Demo + code in the first comment.

---

## 4. r/selfhosted

**Title**: `Plynth — self-hostable multi-tenant SaaS backend, $6 droplet runs the whole stack`

**Body**:

I have been self-hosting a backend layer called **Plynth** (MIT, FastAPI + Postgres + Redis) and figured this sub might find the deploy story interesting. The whole stack — API, worker, Postgres 16, Redis 7, Caddy with auto-TLS — runs on a single $6/mo DigitalOcean droplet (1 GB RAM, 1 vCPU, 25 GB SSD). Same Docker Compose works on a home server or an old NUC.

Repo: `github.com/shubhamkatta/plynth`. Docs: `shubhamkatta.github.io/plynth`.

**The deploy.** `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`. The prod overlay adds `restart: unless-stopped`, drops the bind-mount, runs gunicorn (not uvicorn reload), closes Postgres + Redis ports to the outside (only reachable inside the compose network), pins the pgdata bind-mount to `/var/lib/platform/pgdata` so backups and disk moves are trivial, and adds a Caddy container that auto-provisions TLS for your hostname. There is a step-by-step DigitalOcean runbook in `docs/deploy-digitalocean.md` that covers droplet hardening (non-root deploy user, ufw, fail2ban, unattended upgrades, 2 GB swap), DNS, the cert, seeding the first admin, and locking down the default password. ~90 minutes start to finish the first time. Fly.io + Neon + Upstash runbook is also in the docs if you prefer that flavour.

**Why multi-product matters for self-hosters.** This is the bit I think r/selfhosted will care about more than other subs. The whole point of Plynth is that one deployment hosts many independent SaaS-style apps with full isolation. So one $6 droplet can run, for example, your home dashboard's API + a small B2C side project + an internal tool you want to share with three friends, each with its own tenants, users, plans, and audit log. Adding a new product is one API call, no infra change, no new container. For folks who run a stack of small apps and hate maintaining N copies of the auth and billing layer, this collapses it to one.

**Memory at idle.** Total ~400 MB on the $6 box. Python container is ~120 MB at runtime (`python:3.12-slim` multi-stage), Postgres + Redis are the rest. The droplet has a 2 GB swap file configured in the runbook to absorb spikes. If you want headroom, the $12 / 2 GB plan is one click — same setup, no migration.

**Backups.** `scripts/backup.sh` ships in the repo. `pg_dump` from inside the db container, gzipped on the host, sanity-checked (refuses dumps under 1 KB), uploaded to Backblaze B2 with a timestamped filename, local copies pruned after 7 days. Crontab line: `13 3 * * * cd /opt/platform && B2_BUCKET=... ./scripts/backup.sh`. B2 cost at this scale is about a cent a month — the first 10 GB is free anyway. Test your restores: the runbook has a worked example of `b2 file download ... | gunzip | psql`.

**Updates.** `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build && docker compose ... exec api python -m scripts.migrate`. That's it. Migrations are idempotent. Rollback is `git reset --hard <prev-sha> && up -d --build` — and the runbook spells out the Alembic downgrade flow for bad schema changes.

**No service lock-in.**
- No managed-DB requirement. Bring your own Postgres 16 — the compose file gives you one, but a managed Postgres or your existing pg server works identically.
- No Stripe requirement. There is a mock billing driver baked in for dev. The provider interface is one file (`app/providers/billing/<name>.py`) — swap in Paddle, LemonSqueezy, or nothing at all.
- No external auth. JWT + Argon2id, all local. Google OAuth is an optional per-product toggle.
- No telemetry phoning home. Logs are structlog JSON to stdout — pipe wherever you want (Loki, Vector, plain files).

**Migration off the droplet, when you outgrow it.** Documented path: take a final `pg_dump -Fc`, restore into RDS or Neon, change `DATABASE_URL` on a bigger box, flip the DNS. No code changes. Same Dockerfile, same compose, same secrets. The whole point of this stack is portability.

What I'd love to know from this sub: what's missing for *your* self-host setup? The runbook is open to PRs and I'm happy to add a Unraid / Synology / k3s recipe if anyone wants to co-write one. Honest critique on the backup script and the Caddyfile especially welcome.

---

## Comment templates (use only if asked)

**"How is this different from Supabase?"**

Honest answer: Supabase wins when you're shipping one product fast and want hosted Postgres + Auth + Storage + a JS SDK out of the box. Plynth wins when you're shipping multiple products on shared infra, want strict `(product_id, tenant_id)` isolation enforced at the ORM layer (not just RLS), want the billing + credits + audit machinery included, and prefer Python + self-host. Different sweet spots.

**"Why not use Django?"**

Honest answer: Django + django-tenants gets you partway and is great if you're already a Django shop. Plynth differs in three ways — async-native end to end (FastAPI + async SQLAlchemy + asyncpg, no sync DB calls anywhere in `app/`), multi-product as a first-class concept rather than schema-per-tenant, and the billing state machine + credits ledger + audit log are included instead of bolted on.

**"Looks like marketing"**

Fair pushback. The code is the substance — repository-layer isolation in `app/repositories/base.py`, RBAC matcher in `app/services/rbac.py`, 200+ tests in `tests/`. If something specific is missing, open an issue and I'll either fix it or document why it's out of scope.

---

## After the posts

- Cross-link in the GitHub Discussions ("we got some great feedback on r/Python — thread here") to drive a flywheel
- DM 2-3 commenters who gave substantive feedback offering them a contributor shout-out if they want to pick up an issue
- If a post sinks (< 10 upvotes in 2 hours), don't repost — wait a month and try a different angle
