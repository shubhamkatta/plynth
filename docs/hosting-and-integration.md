# Hosting & Integration

## Hosting — pick by budget

Same stack everywhere: Postgres 16, Redis 7, FastAPI, arq worker. All
runnable from the existing `docker-compose.yml`.

| Tier | Provider | Cost / month | Notes |
| --- | --- | --- | --- |
| Free | **Fly.io** | $0–10 | Generous free tier: app + worker as separate machines; Postgres 1 GB; pair with **Upstash Redis** free (10k cmd/day). Scale-to-zero. Best zero-cost start. |
| Free | **Oracle Cloud "Always Free"** | $0 | 4 ARM cores + 24 GB RAM, forever. Run the whole compose file. Trust Oracle's free-tier longevity at your discretion. |
| Cheap | **Hetzner CCX13** | €5.83 (~$6) | 2 vCPU dedicated / 8 GB / 80 GB SSD. Run everything in Docker on one box. Unbeatable price/perf in Europe. Add Backblaze B2 for `pg_dump` backups (~$0.005/GB/mo). |
| Cheap | **Railway / Render** | $5–20 | Easier deploys from Dockerfile, managed Postgres, but pricier as you grow. |
| Mid | **AWS EC2 t4g.small + RDS** | ~$25–40 | t4g.small ARM ~$12, RDS db.t4g.micro ~$15. Worth it once you need Multi-AZ Postgres. |

### Recommended cheapest setup

**Single Hetzner CCX13 + Caddy + Backblaze B2 backups.** Concrete steps:

1. Provision a CCX13 (~€6 / mo). Install Docker.
2. `git clone` this repo; `cp .env.example .env`; rotate every secret.
3. Add **Caddy** as a reverse proxy in `docker-compose.override.yml`:

   ```yaml
   services:
     caddy:
       image: caddy:2-alpine
       restart: unless-stopped
       ports: ["80:80", "443:443"]
       volumes:
         - ./Caddyfile:/etc/caddy/Caddyfile
         - caddy_data:/data
       depends_on: [api]
   volumes:
     caddy_data:
   ```

   `Caddyfile`:

   ```
   api.your-domain.com {
     reverse_proxy api:8000
   }
   ```

   Caddy handles TLS automatically via Let's Encrypt.

4. **Backups** — nightly cron on the host:

   ```bash
   0 3 * * * docker compose exec -T db pg_dump -U platform platform | \
     gzip | b2 upload-stream "$(date +%F).sql.gz" my-backups-bucket -
   ```

5. **DNS** — Cloudflare (free) in front of Caddy for DDoS + the `Cache-Control` headers your app sends.

Total: ~$6–8/mo running multiple products, single tenant on infrastructure
but multi-product / multi-tenant in the app layer.

### Tradeoffs

- **One box** is the cheapest but single point of failure. Suitable for early-stage SaaS; promote to managed Postgres + a second app box once revenue justifies it.
- **Fly.io** auto-scale-to-zero is fantastic for products with bursty traffic — pay only for actual seconds of CPU. Cold start ~1s.
- **RDS / Cloud SQL** are worth it the moment you need point-in-time recovery without scripting it yourself.

## Integration — how other products consume the platform

Each product (web app, Electron, Windows installer, mobile, etc.) is an
**HTTP API client** of this platform. The platform itself is the only
server-side component you operate; each product app talks to it over
HTTPS.

### What every product client needs to know

1. **Its product slug** — bake it into the build config.
2. **The platform's base URL** — e.g. `https://api.your-domain.com`.
3. **How to send headers**:
   - Public requests (login, register, plans list): `X-Product-Slug: <slug>`
   - Authenticated requests: `Authorization: Bearer <accessToken>` (slug optional — JWT carries it)
4. **Token storage** — keep `accessToken` (~15 min TTL) in memory, `refreshToken` (~30 day TTL) in secure storage (Keychain / Keystore / encrypted file).
5. **Refresh flow** — on 401, call `POST /api/v1/auth/refresh` with the refresh token; retry the original request with the new access token.

### Pattern A — browser / mobile / desktop directly to platform (simplest)

```
[Web app / Mobile app]
       │  HTTPS
       ▼
[Platform API]
       │
       ├── Postgres
       └── Redis
```

Best for thin clients. The platform is the only backend. CORS allows the
product's origin(s).

### Pattern B — product backend in front of the platform

```
[Product UI] → [Product backend (its own services)] → [Platform API]
                                                       │
                                                       ├── Postgres
                                                       └── Redis
```

Use when a product has its own server logic that wraps platform calls or
adds product-specific endpoints. The product backend acts as a service
account against the platform.

For server-to-server calls today, create a normal user with the right role
and store its long-lived refresh token in the product backend's secrets.
Better: add a *service account / API key* concept (a `/api/v1/api-keys`
endpoint that mints tokens that don't expire). That's a small,
well-defined extension — happy to ship it when needed.

### Pattern C — product publishes events back to platform

Webhooks from third parties (Stripe → platform) already work. The reverse
direction (platform → product) isn't built in. If a product needs to know
when a credit balance hits zero or a subscription cancels, two options:

1. **Poll** — product backend calls `GET /api/v1/credits/wallets` on a schedule.
2. **Outbound webhooks** — add a table `webhook_endpoints (product_id, url, secret, event_types[])` and have `audit.record` fan out matching events to subscribed URLs (HMAC-signed). Out of scope today; ~1 day of work.

### CORS for product frontends

Add each product's origin to `CORS_ORIGINS` in the platform's `.env`:

```
CORS_ORIGINS=["https://producta.example.com","https://productb.example.com","https://app.acme.io"]
```

### Sharing the Postman collection

`docs/postman_collection.json` is a complete v2.1 collection covering
every endpoint. Import it into Postman, set three variables (`baseUrl`,
`productSlug`, `platformAdminToken`), run **Auth → Register** or
**Login** — `accessToken` + `refreshToken` populate automatically. Hand
this file to anyone integrating with the platform.

### Versioning & breaking changes

The API is mounted at `/api/v1`. Breaking changes go to `/api/v2`; both
mount points run side by side during a deprecation window. Add the v2
router under `app/api/v2/` and register it in `app/main.py`.

## Parent / child company access

> **Implemented.** A parent / admin company user *can* access child
> company data and switch context into a child via the
> `X-Acting-Tenant-Slug` header. The rest of this section describes the
> contract; full reference lives in `docs/multi-tenancy.md`.

### What's modeled

- `Tenant.parent_id` and `Tenant.is_root` — tenants form a one-level tree (root → child workspaces / subsidiaries).
- `UserRole.scope_tenant_id` — a binding can be scoped to a specific child tenant ("Alice is admin in child-A, member in child-B"); evaluated by `user_has_permission` against the current scope.
- A user has exactly one *home* `tenant_id` (where they were created); requests scope to the *effective* tenant (home, or child when acting-as).

### Three gates

A switch via `X-Acting-Tenant-Slug: <child-slug>` requires all of:

1. **Hierarchy** — target has `parent_id == user.tenant_id`.
2. **Configuration** — both default `true`:
   - Product setting: `Product.settings.features.allow_parent_child_access`
   - Parent-tenant setting: `Tenant.settings.allow_child_access`
3. **RBAC** — user has *either*:
   - `tenants:act_as_child` permission in their home context (owner has it via `*:*`, admin has it by default), OR
   - any `UserRole` with `scope_tenant_id == target.id`.

### What's enforced

- Without the header, the JWT `tid` claim pins the user to their home tenant — they only see their own data.
- With the header, every query in the request is scoped to the child (users / roles / subscriptions / credits / audit). The JWT itself is unchanged.
- `audit_log.acting_from_tenant_id` records the user's home tenant on every action performed via act-as, so audit reconstructs "who in parent X did this in child Y".

### Discovery

`GET /api/v1/tenants/children` returns every direct child with `can_act_as` + a `reason` field for any "no" — drop straight into a "switch tenant" picker.

### Operating recipe

```bash
# As an owner / admin of parent tenant "acme":
TOKEN="<your access token>"

# 1. See which children you can act as.
curl -s -H "Authorization: Bearer $TOKEN" \
        -H "X-Product-Slug: platform" \
     https://api.example.com/api/v1/tenants/children

# 2. Switch into child-east and list its users.
curl -s -H "Authorization: Bearer $TOKEN" \
        -H "X-Product-Slug: platform" \
        -H "X-Acting-Tenant-Slug: child-east" \
     https://api.example.com/api/v1/users
```

### Locking it down

Disable globally for a product (admin call):

```python
# Sets Product.settings.features.allow_parent_child_access = False
# in the relevant Product row.
```

Disable for a specific parent tenant (e.g. compliance carve-out):

```python
# Sets Tenant.settings.allow_child_access = False on that tenant.
```

Either flag → 403 on switch, `can_act_as = false` in the discovery list with a reason explaining which gate fired.

### Summary

| Need | Status |
| --- | --- |
| Parent admin views own data | ✅ default |
| Parent admin lists children they can act as | ✅ `GET /tenants/children` |
| Parent admin acts inside a child tenant | ✅ `X-Acting-Tenant-Slug` header |
| Delegated admin only for a specific child | ✅ `UserRole.scope_tenant_id == child.id` |
| Disable per product | ✅ `Product.settings.features.allow_parent_child_access` |
| Disable per parent | ✅ `Tenant.settings.allow_child_access` |
| Audit shows acting-from | ✅ `audit_log.acting_from_tenant_id` |
| Same user belongs to two unrelated tenants | ❌ each registration is a distinct user (intentional — keeps audit clean) |
| Parent admin sees aggregated data across all children | ❌ not built — use act-as one child at a time, or add a "tenant IN (...)" repository mode if you need a cross-child report view |
