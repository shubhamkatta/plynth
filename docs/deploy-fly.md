# Deploying to Fly.io + Neon + Upstash

Free-tier production stack. ~$3–5/month at idle once Fly's trial credit is
spent; scales linearly until you outgrow the managed addons (see "When to
move off" below).

## Component map

| Concern | Provider | Free tier | Paid step | Why |
| --- | --- | --- | --- | --- |
| API + worker | Fly.io | Trial credit, then ~$0.0000019/s per shared-cpu-1x 256 MB machine | $2.70/mo per always-on 256 MB machine | Multi-process from one image; auto-suspend; great regions |
| Postgres | Neon | 0.5 GB / 1 project / autosuspend | $19/mo Launch (10 GB) | asyncpg-native; database branching for previews |
| Redis | Upstash | 10k cmd/day / 256 MB | $0.20 per 100k cmd | Standard `redis://` URL; pay-per-command |
| Email | Resend | 100/day, 3000/mo | $20/mo (50k) | Drop into `app/providers/notifications.py` |
| DNS / WAF | Cloudflare | Free | — | Front the Fly app; rate-limit DDoS |

## One-time provisioning

### 1. Neon — Postgres

```bash
# Sign up at neon.tech → New project → choose nearest region.
# Copy the *pooled* connection string from "Connection details" → "Pooled":
#   postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
# Convert prefix for asyncpg:
#   postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
```

> Use the **pooled** endpoint. Neon's compute can autosuspend; the pooler keeps Fly machines from hammering wake-ups.

### 2. Upstash — Redis

```bash
# console.upstash.com → Create database → "Redis" → nearest region → "Free".
# Copy the connection string:
#   rediss://default:pass@usw1-xxx.upstash.io:6379
# Note the `rediss://` (TLS). asyncio-redis and arq both handle TLS transparently.
```

### 3. Resend (optional, can defer)

```bash
# resend.com → API Keys → Create. Use later when you wire `notifications.send_email`.
```

### 4. Fly — app + machines

```bash
brew install flyctl              # or: curl -L https://fly.io/install.sh | sh
fly auth login
fly auth signup --org personal   # if new

# Create the app (skip if it already exists):
fly apps create product-platform   # name must be globally unique on Fly
# Edit fly.toml line 7 to match this name.

# Set every secret. Generate fresh values:
fly secrets set \
  JWT_SECRET="$(openssl rand -hex 32)" \
  DATABASE_URL="postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require" \
  REDIS_URL="rediss://default:pass@usw1-xxx.upstash.io:6379" \
  PLATFORM_ADMIN_TOKEN="$(openssl rand -hex 32)" \
  BILLING_PROVIDER="mock" \
  CORS_ORIGINS='["https://producta.example.com","https://productb.example.com"]'
# Add STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET when you connect Stripe.

# Deploy.
fly deploy

# Seed the default product + plans + admin (runs against the production DB):
fly ssh console -C "python -m scripts.seed"

# Hit your app:
fly status                       # shows public URL like https://product-platform.fly.dev
curl https://product-platform.fly.dev/health
```

### 5. Custom domain (optional, free)

```bash
fly certs add api.your-domain.com
# Add the CNAME record Fly tells you to add at your DNS provider.
fly certs check api.your-domain.com   # wait until "Verified"
```

Put Cloudflare in front (DNS-only mode is fine; you don't need proxied since Fly does TLS).

## Day-2 operations

### Deploys

```bash
fly deploy                      # full deploy; runs `alembic upgrade head` first
fly deploy --strategy immediate # skip rolling for hotfixes
fly releases                    # list recent deploys
fly rollback                    # revert to previous release
```

### Logs

```bash
fly logs                        # tail combined
fly logs --instance <id>        # one machine
fly logs --process worker       # one process
```

structlog JSON makes `fly logs | jq` extremely effective.

### Migrations

`fly deploy` runs `alembic upgrade head` automatically (see `release_command` in `fly.toml`). If it fails, the deploy aborts and the previous version keeps serving — Fly's release model is forgiving.

For a manual migration (e.g. between deploys):

```bash
fly ssh console -C "alembic upgrade head"
fly ssh console -C "alembic downgrade -1"
```

### Secrets rotation

```bash
fly secrets set JWT_SECRET="$(openssl rand -hex 32)"
# Triggers a rolling restart automatically.
```

Rotating `JWT_SECRET` invalidates every issued token — users must re-login. Rotate `PLATFORM_ADMIN_TOKEN` whenever it leaks.

### Scaling

```bash
fly scale count api=2                          # horizontal
fly scale memory 512 --process-group api       # vertical
fly scale show
```

### Backups (Neon does this for you)

Neon takes continuous backups + supports PITR within the retention window (free: 24h, paid: 7d / 30d). For peace of mind, schedule a weekly logical dump to B2:

```bash
fly ssh console -C "pg_dump $DATABASE_URL | gzip > /tmp/dump.sql.gz"
fly ssh sftp shell                # then `get /tmp/dump.sql.gz`
```

Or use [Neon's branching](https://neon.tech/docs/guides/branching) as a "Friday safety branch" you can roll back to.

## When to move off (and where to)

Triggers + the typical next step:

| Signal | What it means | Next step |
| --- | --- | --- |
| Neon storage > 500 MB | Free tier exceeded | Neon Launch ($19/mo, 10 GB) or migrate to **DigitalOcean managed Postgres** ($15/mo, 1 GB) / **AWS RDS db.t4g.micro** (~$15/mo) |
| Upstash > 10k cmd/day | Free quota exceeded | Upstash Pay-as-you-go (~$1–5/mo at small scale) or self-host Redis on a small VPS |
| Fly bill > $30/mo | App is no longer tiny | Move to one **DigitalOcean Droplet** ($6/mo, 1 vCPU/1 GB) or **Hetzner CCX13** (~$6/mo) running the existing docker-compose; managed DB stays where it is |
| Single-region latency complaints | Customers in another continent | Add a Fly region with `fly scale count api=1 --region <eu/asia>` and a read-replica in Neon |
| Compliance ask (SOC2 / HIPAA) | Auditors want named providers + audit logs | Move to AWS (RDS + Fargate or EC2) or GCP (Cloud SQL + Cloud Run); both work without code changes — the scaffold is provider-neutral |

The migration is mostly DNS + secrets:
1. Stand up the new environment (e.g. RDS + ECS).
2. `pg_dump | pg_restore` from Neon → RDS (do it twice: dry run, then with a maintenance window).
3. Repoint DNS at the new ingress.
4. Tear down Fly app.

Because the entire app speaks standard Postgres + Redis + Docker, none of the app code changes. The compose file you used in local dev *is* the production manifest on a VPS — only the orchestrator changes.

## Things that bite you on Fly

- **Cold starts**: first request after idle takes ~150 ms (with `suspend`, much worse with `stop`). Acceptable for everything except realtime/streaming.
- **arq + scale-to-zero**: the worker must NOT auto-stop or cron jobs silently skip. The provided `fly.toml` keeps the worker at `min_machines_running = 1`.
- **Neon autosuspend wake**: first query after 5 min idle adds ~1 s. Mostly hidden by the API cold start. To avoid: send a tiny query every 4 min (a `/ready` cron) — or upgrade to a Neon paid plan that disables autosuspend.
- **Region pinning**: machines stick to `primary_region`. Move with `fly deploy --regions iad,sjc` after editing the manifest.
- **No persistent disks needed** — DB is Neon, cache is Upstash. If you ever attach a Fly volume (e.g. for sqlite), it pins the machine to one region.
- **Free tier IPv4** — Fly now charges ~$2/mo per shared IPv4. Use `fly ips list` to check, `fly ips release <ip>` if you only need IPv6 (rarely viable for end-users).

## Cost cheat sheet

| Load | Fly | Neon | Upstash | Total |
| --- | --- | --- | --- | --- |
| Idle / hobby | $0–3 | $0 | $0 | **≤ $5/mo** |
| 1k users, < 100 req/min | $5–10 | $0 | $0 | **~$10/mo** |
| 10k users | ~$25 | $19 (Launch) | ~$5 | **~$50/mo** |
| 100k users | $80+ | $69+ | $20+ | move to VPS or AWS (~$60/mo) |

The "move off" signal usually arrives at the ~$50/mo mark — that's when a $6 DigitalOcean droplet + a $15 managed Postgres equals or beats the managed stack on cost, with marginally more ops work.
