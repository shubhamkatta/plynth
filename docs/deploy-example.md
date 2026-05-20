# Deploy `plynth-api` → `api.example.com`

End-to-end runbook for the **first** production deploy of this scaffold
under the `example.com` domain. Follow it top-to-bottom once;
after that, day-to-day deploys are just `fly deploy`.

Stack: **Fly.io** (API + worker) · **Neon** (Postgres) · **Upstash**
(Redis) · **Cloudflare** (DNS + WAF). Single API endpoint
`https://api.example.com` serves every product via the
`X-Product-Slug` header.

> Generic recipe (provider-agnostic): `docs/deploy-fly.md`.
> Architecture / contracts: `docs/ARCHITECTURE.md`.

---

## Pre-flight checklist

Before starting, have:

- [ ] You own `example.com` at a registrar.
- [ ] A GitHub account that can `git push` to `plynth/generic-product-scaffold` (you do — pushed earlier).
- [ ] A password manager open to store the 4 secrets you'll generate.
- [ ] About **90 minutes** the first time. Re-deploys after this take seconds.

Things you'll create accounts for: **Cloudflare**, **Neon**, **Upstash**,
**Fly.io**. All have free tiers sufficient for Phase 1.

---

## Step 1 — Cloudflare: move DNS + base records

**Why first:** every other step ends in "add a DNS record". Get DNS
under control before anything else.

1. Sign up at [cloudflare.com](https://cloudflare.com) → **Add a site** → `example.com` → Free plan.
2. Cloudflare scans existing records — review, keep what's there.
3. Cloudflare gives you **two nameservers** (e.g. `lara.ns.cloudflare.com`, `xyz.ns.cloudflare.com`).
4. Log in to your **registrar** (GoDaddy / Namecheap / wherever you bought the domain) → **Nameservers** → replace with Cloudflare's two.
5. Wait for propagation (5 min – 2 hours). Check with:
   ```bash
   dig +short NS example.com
   # expect Cloudflare nameservers
   ```
6. Back in Cloudflare → **DNS** → add base records:

| Type | Name | Value | Proxy | Notes |
|---|---|---|---|---|
| `A` | `@` (root) | `192.0.2.1` (placeholder until you have a landing site) | 🟠 Proxied | replace later with Cloudflare Pages or marketing site |
| `CNAME` | `www` | `example.com` | 🟠 Proxied | |
| `TXT` | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` | — | Cloudflare Email Routing SPF |

7. (Optional) **Email → Email Routing** → enable. Forward `hello@`, `support@`, `billing@` to your Gmail. Free.

**Exit:** `dig +short NS example.com` returns Cloudflare nameservers.

---

## Step 2 — Neon: provision Postgres

1. Sign up at [neon.tech](https://neon.tech) → **New project**.
2. Name: `plynth-api`. **Region: AWS `ap-south-1` (Mumbai)** to match Fly's `bom` region — same datacenter campus, single-digit-ms latency.
3. Postgres version: **16**.
4. Once created, in **Connection details** → set the **Connection string** dropdown to **Pooled connection**. Copy it. It looks like:
   ```
   postgresql://platform_owner:****@ep-aged-leaf-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require
   ```
5. **Convert the prefix** for asyncpg by changing `postgresql://` → `postgresql+asyncpg://`:
   ```
   postgresql+asyncpg://platform_owner:****@ep-aged-leaf-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require
   ```
6. Store in your password manager as **`DATABASE_URL`**.

**Exit:** you have the asyncpg-prefixed URL in your password manager.

---

## Step 3 — Upstash: provision Redis

1. Sign up at [console.upstash.com](https://console.upstash.com) → **Create database** → **Redis**.
2. Name: `plynth-api-redis`. Region: **AWS Mumbai `ap-south-1`**. Type: **Regional**. Tier: **Free**.
3. Once created → **Connect** → copy the **`rediss://`** URL (TLS). Looks like:
   ```
   rediss://default:****@apt-koi-12345.upstash.io:6379
   ```
4. Store in your password manager as **`REDIS_URL`**.

**Exit:** you have the `rediss://` URL.

---

## Step 4 — Generate platform secrets

Open a terminal and generate three secrets. Store each in your password manager.

```bash
openssl rand -hex 32   # → JWT_SECRET
openssl rand -hex 32   # → PLATFORM_ADMIN_TOKEN
openssl rand -hex 32   # → (reserve; you'll use this for STRIPE_WEBHOOK_SECRET later)
```

**Why each matters:**
- `JWT_SECRET` — signs every access + refresh token. **Rotating it logs every user out** of every product. Keep it stable.
- `PLATFORM_ADMIN_TOKEN` — the shared secret for `/api/v1/admin/products` (creating new products). **Treat it like an AWS root key**. Never ship to a client. Only your ops machine + the platform itself ever see it.

---

## Step 5 — Fly.io: install + auth + create app

```bash
# Install (skip if already done)
brew install flyctl       # or:  curl -L https://fly.io/install.sh | sh

# Auth
fly auth signup           # or `fly auth login` if account exists
fly auth whoami           # confirms your email

# From the repo root:
cd <repo>

# The fly.toml is already set to:
#   app = "plynth-api"
#   primary_region = "bom"
# Just create the app on Fly:
fly apps create plynth-api
```

If the app name `plynth-api` is taken globally on Fly, edit `fly.toml` line 6 and re-run `fly apps create <newname>`. Suggested fallback: `plynth-api-prod`.

---

## Step 6 — Push secrets to Fly

Paste the URLs and secrets from your password manager. Replace the `<...>` placeholders:

```bash
fly secrets set \
  JWT_SECRET='<your 64-hex JWT_SECRET>' \
  DATABASE_URL='postgresql+asyncpg://platform_owner:****@ep-...-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require' \
  REDIS_URL='rediss://default:****@apt-....upstash.io:6379' \
  PLATFORM_ADMIN_TOKEN='<your 64-hex PLATFORM_ADMIN_TOKEN>' \
  BILLING_PROVIDER='mock' \
  CORS_ORIGINS='["https://example.com","https://www.example.com"]'
```

Stripe stays on `mock` until you actually accept payments — see Step 11.

Verify:
```bash
fly secrets list
# shows secret names + digests (never the values)
```

---

## Step 7 — Deploy

```bash
fly deploy
```

This will:
1. Build the Docker image locally and push to Fly's registry.
2. Run `alembic upgrade head` in a one-shot release machine (per `fly.toml` `release_command`). **The deploy fails if migrations fail** — no half-broken state.
3. Roll out new API + worker machines.

Expected output ends with something like:
```
✓ Machine created and started in xx seconds
✓ Smoke checks for ... passed
```

First deploy takes ~3-5 minutes. Subsequent deploys ~60 seconds.

If the build fails, see § "Troubleshooting" at the bottom.

---

## Step 8 — Seed default product + admin

This populates the `platform` product, default plans (free / pro / enterprise), and the seed admin user:

```bash
fly ssh console -C "python -m scripts.seed"
```

Expect log lines: `seed.product_created`, `seed.plan_created` × 3, `seed.root_tenant_created`, `seed.admin_created`.

**Default admin (change immediately on first login):**
- Email: `admin@example.com`
- Password: `ChangeMeNow123!`

Verify the deploy is alive:
```bash
fly status
fly logs --process api | head -20
curl -s https://plynth-api.fly.dev/health
# {"status":"ok"}
curl -s https://plynth-api.fly.dev/ready
# {"status":"ready"}
```

---

## Step 9 — Attach `api.example.com`

```bash
fly certs add api.example.com
```

Fly prints two records you must add at Cloudflare. They look like:

```
CNAME  api                     plynth-api.fly.dev
A      api                     <Fly IPv4>
AAAA   api                     <Fly IPv6>
```

(Depending on Fly's current cert flow you may also see a `_acme-challenge.api` TXT — add it too.)

In **Cloudflare → DNS → Add record**:

| Type | Name | Value | Proxy status | TTL |
|---|---|---|---|---|
| `CNAME` | `api` | `plynth-api.fly.dev` | **🟢 DNS only (grey cloud)** | Auto |

> **CRITICAL:** set proxy to **DNS only**, not Proxied. Fly does its own TLS — the Cloudflare proxy would intercept the cert challenge and break things. Trade-off: no Cloudflare DDoS/WAF in front of the API. The Fly platform absorbs DDoS adequately for our scale; revisit if you outgrow.

Then wait 30-90 seconds and verify:

```bash
fly certs check api.example.com
# Status: Verified

curl -s https://api.example.com/health
# {"status":"ok"}

curl -s https://api.example.com/ready
# {"status":"ready"}
```

Certificate auto-renews forever. You never touch it again.

---

## Step 10 — Smoke test via Postman

1. Open Postman → **Import** → `docs/postman_collection.json`.
2. Edit collection variables:
   - `baseUrl` = `https://api.example.com`
   - `productSlug` = `platform` (seeded default)
   - `platformAdminToken` = your `PLATFORM_ADMIN_TOKEN`
3. Run the **Admin → List Products** request. Expect `[{slug: "platform", ...}]`.
4. Run **Auth → Register (Individual / B2C)** with a fresh email. Expect `201` and `accessToken` auto-saved.
5. Run **Auth → Me**. Expect 200 with your email + permissions.
6. Run **Plans → List Public Plans** with `X-Product-Slug: platform`. Expect `free` + `pro`.

If all four pass, the platform is **live in production**.

---

## Step 11 — Cost guardrails

Set spending caps **before** you forget. Open the dashboard for each provider:

| Provider | Where | Suggested cap |
|---|---|---|
| Fly.io | dashboard.fly.io → Org → **Billing → Spend cap** | `$20/mo` |
| Neon | console.neon.tech → Settings → **Billing → Spend cap** | `$25/mo` |
| Upstash | console.upstash.com → Account → **Billing** | `$10/mo` |
| Cloudflare | $0 — free plan, no charges possible |

Total max if everything explodes: `$55/mo`. Adjust upward as customers arrive.

Also add **email alerts** at 50% / 80% / 100% of each cap.

---

## Step 12 — Lock down the seed admin

The deploy is public. Do this within 10 minutes:

```bash
# Log in as admin via Postman or curl:
curl -X POST https://api.example.com/api/v1/auth/login \
  -H "X-Product-Slug: platform" -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"ChangeMeNow123!"}'
# Copy access_token from response.

# Change the password:
curl -X POST https://api.example.com/api/v1/auth/password \
  -H "Authorization: Bearer <access>" \
  -H "X-Product-Slug: platform" -H "Content-Type: application/json" \
  -d '{"current_password":"ChangeMeNow123!","new_password":"<long-strong-pw>"}'
```

Store the new password in your password manager under
**`platform admin login`**.

---

## Step 13 — Stripe (only when ready to charge)

Skip this until you have your first paying customer prospect.

1. Stripe dashboard → **Developers → API keys** → copy `sk_test_...` (for sandbox) or `sk_live_...` (production).
2. **Developers → Webhooks → Add endpoint** → URL: `https://api.example.com/api/v1/webhooks/billing`.
   - Events: `invoice.payment_succeeded`, `invoice.payment_failed`, `invoice.paid`.
   - Copy the `Signing secret` (`whsec_...`).
3. Push to Fly:
   ```bash
   fly secrets set \
     BILLING_PROVIDER=stripe \
     STRIPE_API_KEY='sk_...' \
     STRIPE_WEBHOOK_SECRET='whsec_...'
   ```
4. For each `Plan` in the platform, create a matching **Price** in Stripe, then backfill `Plan.provider_refs.stripe = "price_..."` via the API (`PATCH /api/v1/plans/{code}`).

---

## Day-2 operations

| Action | Command |
|---|---|
| Deploy a change | `make deploy` (or `fly deploy`) — runs migrations as `release_command` |
| Tail logs | `make logs` (or `fly logs`) |
| One-off shell | `make prod-shell` (or `fly ssh console`) |
| Re-seed (idempotent) | `make prod-seed` |
| Manual migration | `make prod-migrate` |
| Rotate JWT secret (logs everyone out) | `fly secrets set JWT_SECRET=$(openssl rand -hex 32)` |
| Scale up | `fly scale count api=2` · `fly scale memory 512 --process-group api` |
| Add a region | `fly regions add fra sjc` |
| Roll back the last deploy | `fly releases` → `fly rollback` |

Full reference: `docs/deploy-fly.md`.

---

## Rollback / disaster recovery

| Scenario | What to do |
|---|---|
| Bad deploy | `fly rollback` — promotes the previous release. Migrations were idempotent so DB is fine. |
| Bad migration | `fly ssh console -C "alembic downgrade -1"` then `fly rollback`. |
| Corrupted data | Restore Neon branch from the last good point: console.neon.tech → Branches → Restore. |
| Tokens leaked | `fly secrets set JWT_SECRET=$(openssl rand -hex 32)` — every user re-logs in within 15 min as their access token expires. |
| Platform admin token leaked | Rotate via `fly secrets set PLATFORM_ADMIN_TOKEN=$(openssl rand -hex 32)` immediately. Any ongoing admin scripts will need the new value. |
| Domain compromised | Cloudflare → enable 2FA on the account; rotate registrar password; renew certs. |

---

## When you outgrow the free tier

Watch list (set alerts so you find out early):

| Signal | Trigger | What to do |
|---|---|---|
| Neon storage > 400 MB | approaching 500 MB cap | upgrade Neon Launch ($19/mo, 10 GB) OR migrate to DO managed PG ($15/mo) |
| Upstash > 8k cmd/day | approaching 10k cap | upgrade pay-per-cmd (~$1-5/mo at small scale) |
| Fly bill > $25/mo | approaching cap | consider single Hetzner CCX13 ($6/mo) running `docker-compose.yml`; managed DB stays |
| Multi-region latency complaints | users in other continents | `fly regions add fra sjc syd` (still on Fly, ~$3/region for the same machine sizes) |

**Migration path off Fly = just DNS.** Bring up new infra, `pg_dump | pg_restore` from Neon, change the CNAME `api → <new-host>`, tear down Fly. No code changes — that's the whole point of the Docker-Compose-based design.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `fly deploy` build fails on `pip install` | network blip on Fly's builder | re-run `fly deploy` |
| `release_command` (alembic) fails | wrong `DATABASE_URL` prefix or unreachable Neon | check `fly secrets list`; ensure `postgresql+asyncpg://` prefix; test from laptop with `psql "<original postgresql:// url>"` |
| `/ready` returns 503 | DB or Redis unreachable | `fly logs --process api`; check Neon + Upstash status; verify `?sslmode=require` |
| Cert check stuck on `Awaiting configuration` after 5 min | DNS not propagated | `dig +short CNAME api.example.com` should return `plynth-api.fly.dev`. If empty, wait or recheck Cloudflare record. |
| 401 on `/auth/login` with seed password | already rotated | use the new password from your manager |
| Worker not running cron | machine count = 0 | `fly status --process worker`; ensure `min_machines_running = 1` in `fly.toml` |
| Stripe webhook returns 400 | signature mismatch | `fly secrets list` — confirm `STRIPE_WEBHOOK_SECRET` matches dashboard. Restart with `fly secrets set` if doubt. |
| `fly logs` shows `MissingGreenlet` | bug in code | should not happen in production; if so, file an issue + rollback |
| Sudden Fly bill spike | runaway machines | `fly scale count api=1`; check for stuck builds with `fly builds list` |

---

## Bookmark this URL

`https://api.example.com` — your platform's address for the
next decade. What runs behind it can change; the address stays the
same. Every product (Electron, web, mobile) hard-codes this in its
build config + sends `X-Product-Slug: <theirs>` on every call.

When you ship a second product, repeat **Step 10** with a different
product slug — same API, no new infrastructure, no new domain.
