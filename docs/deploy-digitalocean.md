# Deploy → `api.example.com` on DigitalOcean ($6/mo)

End-to-end runbook for the **cheapest production-grade deploy** of this
scaffold: one $6/mo DigitalOcean droplet running the existing
`docker-compose.yml` + a production overlay, fronted by Caddy for
auto-TLS, with nightly backups to Backblaze B2.

Same end result as Fly: `https://api.example.com` is live and
every product hits it. Different infra. Migration to Fly / AWS later is
a `pg_dump | ssh` + DNS flip (covered in § 14).

> Architecture / contracts: `docs/ARCHITECTURE.md`.
> Fly-equivalent runbook: `docs/deploy-plynth.md`.

Total time the first time: **~90 minutes**. Total cost: **~$8/mo all-in**.

---

## Pre-flight checklist

- [ ] You own `example.com` (you do).
- [ ] Cloudflare manages DNS for it (from `deploy-plynth.md` § 1) — if not, do that section first.
- [ ] An SSH key on your laptop (`ls ~/.ssh/id_ed25519.pub` — if not, run `ssh-keygen -t ed25519`).
- [ ] About **90 minutes** the first time.

Accounts you'll need (all have free signups):

- **DigitalOcean** — $6/mo droplet
- **Backblaze B2** — 10 GB free for backups
- **UptimeRobot** — free uptime monitoring (optional but recommended)

---

## Step 1 — Provision the droplet

1. Sign up / log in at [cloud.digitalocean.com](https://cloud.digitalocean.com).
2. **Create → Droplet** with:
   - **Region**: `Bangalore (BLR1)` — lowest latency from India.
   - **Image**: Ubuntu 24.04 (LTS) x64.
   - **Type**: **Basic** → **Premium AMD** → **`$6/mo` (1 GB / 1 vCPU / 25 GB SSD)**.
   - **Authentication**: SSH key — paste `~/.ssh/id_ed25519.pub`.
   - **Hostname**: `plynth-api`.
   - **Backups**: leave OFF (we do our own to B2 — $1.20/mo cheaper).
3. Click Create. ~60 sec.
4. Note the **public IPv4** — let's call it `$DROPLET_IP`.

Verify access:
```bash
ssh root@$DROPLET_IP
# you should land in the droplet
```

> **Sizing note**: $6 (1 GB RAM) is tight running Postgres + Redis + API + worker side-by-side. We add a 2 GB swap file in Step 2 to absorb spikes. If you'd rather not worry about it, the $12 plan (2 GB RAM) is the next step up — same setup, just one click.

---

## Step 2 — Harden the box (15 min)

While `ssh root@$DROPLET_IP`:

```bash
# 2.1 — System update
apt update && apt upgrade -y && apt autoremove -y

# 2.2 — Create a non-root deploy user with sudo
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
rsync -a ~/.ssh /home/deploy/
chown -R deploy:deploy /home/deploy/.ssh

# 2.3 — Lock down SSH (no password auth, no root login)
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# 2.4 — Firewall (ufw)
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp        # http (Caddy redirects to https)
ufw allow 443/tcp       # https
ufw allow 443/udp       # http/3
ufw --force enable

# 2.5 — Unattended security updates
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades   # answer Yes

# 2.6 — fail2ban (blocks repeated bad SSH attempts)
apt install -y fail2ban
systemctl enable --now fail2ban

# 2.7 — Swap file (2 GB) — keeps the box alive under memory spikes
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf
```

**Test** the new user from a *new* terminal on your laptop:
```bash
ssh deploy@$DROPLET_IP
sudo whoami        # → root
```

Then `exit` the root session — from now on use `deploy@`.

---

## Step 3 — Install Docker + Compose plugin (5 min)

As `deploy@`:

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) \
    signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
                    docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker deploy
# log out + back in for the group to apply
exit
ssh deploy@$DROPLET_IP

docker version
docker compose version    # should show v2.x
```

---

## Step 4 — Clone the repo + secrets (10 min)

```bash
sudo mkdir -p /opt/platform
sudo chown deploy:deploy /opt/platform
cd /opt/platform

# Clone over HTTPS (no key needed for a public clone; for private repos,
# either add a deploy key or use a fine-grained PAT via gh).
git clone https://github.com/plynth/generic-product-scaffold.git .

# Generate secrets (do these on the droplet so they never leave it)
JWT_SECRET=$(openssl rand -hex 32)
PLATFORM_ADMIN_TOKEN=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 24)

# Write the .env file. Note: db hostname stays `db` (compose service name);
# the prod overlay binds db port to nothing — accessible only inside the
# compose network.
cat > .env <<EOF
APP_ENV=production
APP_NAME=plynth-api
APP_DEBUG=false
APP_LOG_LEVEL=INFO

API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=2
API_PREFIX=/api/v1
CORS_ORIGINS=["https://example.com","https://www.example.com"]

JWT_SECRET=$JWT_SECRET
JWT_ALGORITHM=HS256
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=2592000
PASSWORD_MIN_LENGTH=12

DATABASE_URL=postgresql+asyncpg://platform:${POSTGRES_PASSWORD}@db:5432/platform
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_ECHO=false

REDIS_URL=redis://redis:6379/0

BILLING_PROVIDER=mock
STRIPE_API_KEY=
STRIPE_WEBHOOK_SECRET=

DEFAULT_TRIAL_DAYS=14
GRACE_PERIOD_DAYS=7
RATE_LIMIT_PER_MINUTE=120

PLATFORM_ADMIN_TOKEN=$PLATFORM_ADMIN_TOKEN
EOF

chmod 600 .env

# Copy the values you'll need to your password manager:
echo "JWT_SECRET=$JWT_SECRET"
echo "PLATFORM_ADMIN_TOKEN=$PLATFORM_ADMIN_TOKEN"
echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"

# Tell the db service to use the password we set
sed -i "s|POSTGRES_PASSWORD: platform|POSTGRES_PASSWORD: $POSTGRES_PASSWORD|" docker-compose.yml
```

> **Important:** `.env` lives only on the droplet. Don't commit it.
> The repo's `.gitignore` already excludes it.

---

## Step 5 — Prepare the production overlay + Caddy

The repo already ships `docker-compose.prod.yml` (production overlay)
and `Caddyfile.example`. You just need to:

```bash
# Use the example Caddyfile (hostname already correct for plynth)
cp Caddyfile.example Caddyfile

# If you're on a different hostname, edit it:
# nano Caddyfile

# Make sure the dump destination exists (used by docker-compose.prod.yml's
# Postgres bind-mount):
sudo mkdir -p /var/lib/platform/pgdata
sudo chown -R 999:999 /var/lib/platform/pgdata     # postgres uid inside container
```

What the prod overlay changes vs `docker-compose.yml`:
- Adds `restart: unless-stopped` to every service.
- Drops the `./:/app` bind-mount (uses baked-in code).
- API runs `gunicorn` (not `uvicorn --reload`) on `127.0.0.1:8000` only.
- Postgres + Redis ports closed to the outside.
- Postgres data → `/var/lib/platform/pgdata` (host) so backups + future migrations are trivial.
- Adds a `caddy` service on :80/:443 that auto-provisions TLS for `api.example.com`.

---

## Step 6 — Bring up the stack (5 min)

**Before this step**, you need `api.example.com` DNS pointing at the droplet — Caddy needs that to issue the cert. So:

In **Cloudflare → DNS → Add record**:

| Type | Name | Value | Proxy | TTL |
|---|---|---|---|---|
| `A` | `api` | `$DROPLET_IP` | **🟢 DNS only (grey cloud)** | Auto |

> **CRITICAL:** proxy must be **DNS only**, not Proxied. Caddy does TLS itself — the Cloudflare proxy would intercept the ACME HTTP-01 challenge and break cert issuance. Same trade-off as Fly — you lose Cloudflare's DDoS/WAF in front of the API, but the Droplet's firewall + ufw absorb normal attacks.

Wait 30 sec, verify:
```bash
dig +short A api.example.com
# → your droplet IP
```

Then bring everything up:
```bash
cd /opt/platform
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

First boot takes ~3 min (image build + Postgres init + Caddy fetches cert).

Watch:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy
# look for "certificate obtained successfully"
```

Apply DB migrations:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec api alembic upgrade head
```

Seed default product + admin:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec api python -m scripts.seed
```

Verify the stack is alive:
```bash
curl -s https://api.example.com/health
# {"status":"ok"}

curl -s https://api.example.com/ready
# {"status":"ready"}
```

🎉 You're live.

---

## Step 7 — Smoke test via Postman (10 min)

1. Open Postman → **Import** → `docs/postman_collection.json` (from your laptop's checkout).
2. Edit collection variables:
   - `baseUrl` = `https://api.example.com`
   - `productSlug` = `platform`
   - `platformAdminToken` = the value you saved from Step 4
3. Run **Admin → List Products** → expect `[{slug: "platform", ...}]`.
4. Run **Auth → Register (Individual / B2C)** with a fresh email → expect 201 + token auto-saved.
5. Run **Auth → Me** → expect 200 with your email.
6. Run **Plans → List Public Plans** → expect `free` + `pro`.

If all four pass, the platform is **live in production**.

---

## Step 8 — Lock down the seed admin (5 min)

The deploy is public. Change the default admin password within 10 min:

```bash
# From your laptop (replace TOKEN after login):
curl -X POST https://api.example.com/api/v1/auth/login \
    -H "X-Product-Slug: platform" -H "Content-Type: application/json" \
    -d '{"email":"admin@example.com","password":"ChangeMeNow123!"}'
# copy access_token

curl -X POST https://api.example.com/api/v1/auth/password \
    -H "Authorization: Bearer <access>" \
    -H "X-Product-Slug: platform" -H "Content-Type: application/json" \
    -d '{"current_password":"ChangeMeNow123!","new_password":"<long-strong-pw>"}'
```

Save the new password in your password manager as **`platform admin login`**.

---

## Step 9 — Nightly backups → Backblaze B2 (15 min)

The repo ships `scripts/backup.sh` (already executable). Set it up:

```bash
# 9.1 — Sign up at backblaze.com → My Account → Buckets → Create Bucket
#       Name:    platform-backups   (must be globally unique; prepend something)
#       Files:   Private
#       Lifecycle: Keep prior versions for 30 days

# 9.2 — Create an Application Key scoped to that bucket only.
#       Backblaze → Account → Application Keys → Add a New Application Key
#       Save the keyID and applicationKey.

# 9.3 — On the droplet, install the b2 CLI:
sudo apt install -y python3-pip
pip install --user b2
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

b2 account authorize <keyID> <applicationKey>
b2 bucket list                               # smoke test
```

Test a one-off backup:
```bash
cd /opt/platform
B2_BUCKET=<your-bucket-name> ./scripts/backup.sh
```

Then schedule it:
```bash
sudo touch /var/log/platform-backup.log
sudo chown deploy:deploy /var/log/platform-backup.log

crontab -e
# Add this line (3:13 AM IST daily):
13 3 * * * cd /opt/platform && B2_BUCKET=<your-bucket-name> ./scripts/backup.sh >> /var/log/platform-backup.log 2>&1
```

The script does:
- `pg_dump` from inside the db container, piped through gzip on the host.
- Sanity check (refuse dumps < 1 KB).
- Upload to B2 with timestamped filename.
- Prune local copies older than 7 days.

Cost at your scale: **~$0.01/mo** (Backblaze charges $0.005/GB/mo; first 10 GB free anyway).

---

## Step 10 — Uptime monitoring (5 min, free)

1. Sign up at [uptimerobot.com](https://uptimerobot.com) → free tier (50 monitors).
2. **Add New Monitor**:
   - Type: HTTPS
   - URL: `https://api.example.com/health`
   - Interval: 5 min
   - Alert contact: your email
3. Done. You'll be paged within 5 min if the box goes down.

---

## Day-2 operations

Run all of these from the repo root on the droplet (`cd /opt/platform`).

```bash
# Deploy a new version
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec api alembic upgrade head

# Tail logs (combined)
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Single service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy

# Restart just the API
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart api

# Shell into the api container
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api bash

# Run one-off Python
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec api python -m scripts.seed

# Re-issue Caddy cert (rarely needed; renews automatically)
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart caddy

# Rotate JWT secret (logs every user out within 15 min)
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    up -d --force-recreate api worker

# Check disk / memory
df -h
free -h
docker stats --no-stream
```

> **Tip**: alias the long compose command in `~/.bashrc`:
> ```bash
> alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
> ```
> Then `dcp up -d`, `dcp logs -f api`, etc.

---

## Cost summary

| Item | Monthly |
|---|---|
| DigitalOcean Droplet (1 GB ARM, Bangalore) | $6.00 |
| Cloudflare DNS + free email forwarding | $0 |
| Backblaze B2 backups (≤ 10 GB free tier) | ~$0 |
| UptimeRobot monitoring | $0 |
| Domain `example.com` (already owned) | $0 |
| **Total** | **~$6/mo** |

Plus a one-time $0 for the entire setup if you're patient with Cloudflare's free tier. The next size up ($12 / 2 GB) is one click if you ever want more headroom.

---

## Rollback / disaster recovery

| Scenario | What to do |
|---|---|
| Bad deploy | `git reset --hard <prev-sha> && dcp up -d --build` then re-run migration if needed |
| Bad migration | `dcp exec api alembic downgrade -1` then `git reset --hard <prev-sha> && dcp up -d --build` |
| Corrupted Postgres | Restore from B2: `b2 file download b2://platform-backups/<file> /tmp/restore.sql.gz && gunzip /tmp/restore.sql.gz && dcp exec -T db psql -U platform platform < /tmp/restore.sql` |
| Lost the droplet entirely | Provision new droplet, repeat Steps 2-5, then restore from B2 before Step 6 |
| Tokens leaked | Rotate `JWT_SECRET` via the Day-2 command above |
| Platform admin token leaked | Same — rotate `PLATFORM_ADMIN_TOKEN` in `.env` and `dcp up -d --force-recreate api worker` |

**Test the restore** at least once. Bring up a second droplet temporarily,
restore last night's B2 dump, confirm it loads. Untested backups don't
count.

---

## When to escape this setup

Watch list:

| Signal | Move |
|---|---|
| Droplet RAM consistently > 80% | Upgrade to $12 (2 GB) — one click, no migration |
| Disk > 70% of 25 GB | Resize droplet or move DB to managed Postgres |
| One-box failure = outage you can't tolerate | Move DB to **DO Managed Postgres** ($15/mo, daily backups + PITR) — keep app on droplet |
| Adding a paying customer #2-3 (your trigger) | Move to **AWS** — see § 14 |
| Compliance ask | Move to AWS (SOC2-friendly providers) |

---

## Migration path → AWS (when you have paying customers)

The whole point of this setup is portability. Here's the path:

1. **Spin up RDS** in AWS, `db.t4g.micro` to start (~$13/mo).
2. **Spin up ElastiCache** Redis `cache.t4g.micro` (~$11/mo).
3. **Spin up EC2** `t4g.small` ARM (~$12/mo) OR ECS Fargate (~$25/mo).
4. On the droplet, take a final backup:
   ```bash
   dcp exec -T db pg_dump -U platform -Fc platform > /tmp/final.dump
   ```
5. Restore into RDS:
   ```bash
   pg_restore -h <rds-host> -U <user> -d <dbname> /tmp/final.dump
   ```
6. On the new EC2 / Fargate, set `DATABASE_URL` + `REDIS_URL` to point at RDS + ElastiCache.
7. Bring up the same `docker-compose.yml` + `docker-compose.prod.yml` (or convert to ECS task def).
8. Cutover: change Cloudflare CNAME `api` → new host. **DNS propagation < 60 sec.**
9. Tear down the droplet.

No code changes. Same Dockerfile, same compose, same secrets. The only difference is what's behind the CNAME.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Caddy logs "obtaining certificate" then errors | DNS not pointed at droplet, or proxied through Cloudflare | `dig +short A api.example.com` should = droplet IP; Cloudflare proxy must be DNS-only |
| `docker compose up` fails with `bind: address already in use` | Old Postgres still running, or port 80 occupied | `sudo lsof -i :80 -i :443 -i :5432`; kill the offender |
| API returns 503 from `/ready` | DB not ready yet (first 30 sec), or pgdata permissions wrong | `dcp logs db`; check `/var/lib/platform/pgdata` is owned by `999:999` |
| 502 from Caddy → api | API container OOM'd or crashed | `dcp logs api`; `docker stats`; consider $12 plan or trim worker count to 1 |
| Backup script "ERROR: dump suspiciously small" | DB empty (no users yet) — change check threshold in `scripts/backup.sh`, or ignore until first user |
| Cron not running | `sudo systemctl status cron`; check `/var/log/platform-backup.log`; cron mail to root if it fails |
| Cert renewal fails after 90 days | Cloudflare proxy got switched on, or port 80 blocked | Re-check ufw + Cloudflare proxy = off |

---

## Bookmark this URL

`https://api.example.com` — your platform's stable address.
Same domain whether the backend lives on this droplet, a Fly machine, or
AWS Fargate. Every product (web, Electron, mobile) hard-codes this
plus `X-Product-Slug: <theirs>` on every call.

The two files that drive this whole setup live in the repo:
**`docker-compose.prod.yml`** + **`Caddyfile.example`**. Treat them like
infrastructure-as-code — when you change them, commit + redeploy.
