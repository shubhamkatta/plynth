# Quickstart

Boot the full Plynth stack — Postgres, Redis, the FastAPI API, and the
arq worker — and make your first authenticated call in about five
minutes.

## Prereqs

You only need three things on the host:

- **Docker** (Docker Desktop on macOS / Windows, or Engine + Compose on
  Linux). The default `make up` target uses `docker compose`.
- **Make**. Pre-installed on macOS and most Linuxes. On Windows use WSL2.
- **Python 3.12** — only required if you want to run the test suite or
  the CLI outside the container. The API itself runs inside Docker.

That's it. No global Postgres, no global Redis, no Node toolchain for the
backend.

## Clone & run

```bash
git clone https://github.com/shubhamkatta/plynth.git
cd plynth
cp .env.example .env
make up          # postgres + redis + api + worker
make migrate     # apply schema (Alembic + scripts/migrate.py)
make seed        # default product "platform" + standard plans + admin user
open http://localhost:8000/docs
```

The API is now listening on `http://localhost:8000` and Swagger UI is at
`/docs`. If `open` isn't available (Linux), just visit the URL manually.

## What just happened

`make seed` provisioned a single **product** called `platform` with the
default plan catalogue and a seed administrator. Every public API call
on Plynth carries a `X-Product-Slug` header that selects which product
you're talking to; authenticated calls derive the product from the JWT's
`pid` claim instead, and the two must agree.

!!! warning "Change the seed credentials immediately"
    The seeded admin is `admin@example.com` / `ChangeMeNow123!`. Rotate
    it before exposing the API to anything other than `localhost`. The
    seed script is a development convenience, not a production
    bootstrap step.

You can verify the seed worked by listing plans on the default product:

```bash
curl -H "X-Product-Slug: platform" \
  http://localhost:8000/api/v1/plans
```

## Bootstrap your first product

Real deployments host many products on a single Plynth install. Create
one with the platform admin endpoint, then register a tenant inside it.

=== "curl"

    ```bash
    # 1. Create the product (idempotent on slug)
    curl -X POST http://localhost:8000/api/v1/admin/products \
      -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "ChatBot", "slug": "chatbot"}'

    # 2. Register a B2B tenant inside it
    curl -X POST http://localhost:8000/api/v1/auth/register \
      -H "X-Product-Slug: chatbot" \
      -H "Content-Type: application/json" \
      -d '{"tenant_name": "Acme",
           "tenant_slug": "acme",
           "email": "owner@acme.example.com",
           "password": "S3cretPassword!"}'
    ```

=== "httpie"

    ```bash
    http POST :8000/api/v1/admin/products \
      X-Platform-Admin-Token:$PLATFORM_ADMIN_TOKEN \
      name=ChatBot slug=chatbot

    http POST :8000/api/v1/auth/register \
      X-Product-Slug:chatbot \
      tenant_name=Acme tenant_slug=acme \
      email=owner@acme.example.com \
      password=S3cretPassword!
    ```

=== "Python"

    ```python
    import os, httpx

    base = "http://localhost:8000/api/v1"
    admin = {"X-Platform-Admin-Token": os.environ["PLATFORM_ADMIN_TOKEN"]}

    httpx.post(f"{base}/admin/products", headers=admin,
               json={"name": "ChatBot", "slug": "chatbot"}).raise_for_status()

    httpx.post(f"{base}/auth/register",
               headers={"X-Product-Slug": "chatbot"},
               json={"tenant_name": "Acme", "tenant_slug": "acme",
                     "email": "owner@acme.example.com",
                     "password": "S3cretPassword!"}).raise_for_status()
    ```

The admin endpoint seeds the system roles (`owner`, `admin`, `member`,
`viewer`) automatically. Create plans for the new product via the plans
endpoint — see [Multi-product](multi-product.md).

!!! note "B2B vs B2C — the `tenant_type` field"
    The same `register` flow handles both shapes. Tenants created via
    `POST /auth/register` are **B2B** by default (a company with seats).
    For a single-user **B2C** product, use
    `POST /auth/register-individual` — it creates a synthetic tenant
    bound to one user with the same trial subscription, credits, and
    audit. The `tenant_type` column (`company` vs `individual`) is what
    downstream code branches on. See
    [Multi-tenancy § B2B vs B2C](multi-tenancy.md).

### B2C signup (one user, no company)

```bash
curl -X POST http://localhost:8000/api/v1/auth/register-individual \
  -H "X-Product-Slug: notepad" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com",
       "password": "S3cretPassword!",
       "full_name": "Alice Rivers"}'
```

## Sign in as the admin

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "X-Product-Slug: platform" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com",
       "password": "ChangeMeNow123!"}'
```

The response is a **`TokenPair`** envelope:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 900
}
```

- **`access_token`** is a short-lived JWT (15 min by default). Send it
  as `Authorization: Bearer <access_token>` on every authenticated
  call. It carries `sub` (user id), `tid` (tenant id), and `pid`
  (product id) claims — the product comes from the token, not the
  header, on authenticated routes.
- **`refresh_token`** is long-lived and single-use. POST it to
  `/auth/refresh` to mint a new pair. It's stored server-side so
  revocation works.
- **`expires_in`** is seconds until the access token expires — use it
  to schedule the refresh.

Use it immediately to fetch your own profile:

```bash
curl http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

## Next steps

- [Architecture](architecture.md) — the source of truth: HLD, LLD,
  data model, route catalogue, RBAC codes, and the Jobs / Storage API
  contracts.
- [Integration guide](INTEGRATION.md) — how to plug your real product
  onto the platform layer without breaking tenant or product
  isolation.
- [`examples/nextjs-starter/`](https://github.com/shubhamkatta/plynth/tree/main/examples/nextjs-starter) —
  a minimal Next.js 14 frontend that handles login, refresh, and an
  authenticated read against a running Plynth backend. Copy it and
  point `NEXT_PUBLIC_API_BASE` at your deployment.
