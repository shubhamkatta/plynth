# plynth_cli

Terminal-first admin/ops client for the [Plynth](../README.md) multi-tenant
SaaS platform. Mirrors the surface area of `apps/admin-electron/` for
shell users — every operation goes through the documented public REST
API (`/api/v1/*`); no privileged surface.

## Install

Install the platform with the `cli` extras — this pulls in `click`,
`rich`, and the local `plynth-sdk` package the CLI wraps:

```bash
pip install -e ".[cli]"
```

That registers a `plynth` console script:

```bash
plynth --help
```

(Equivalent: `python -m plynth_cli --help`.)

## Architecture

The CLI is a thin wrapper around [`plynth-sdk`](../sdks/python/). All
HTTP plumbing — header building, refresh-once-on-401, idempotency keys,
error envelope parsing — lives in the SDK. The CLI adds:

- **Session storage** to `~/.config/plynth/config.json` (mode 0600)
  via a `TokenStore` adapter, alongside non-token state like the
  platform-admin token, default product slug, and acting-tenant slug.
- **Click subcommands** that map onto SDK resource methods.
- **Rich-formatted output** (with a plain fallback when rich isn't
  installed).

If you're building an integration in Python rather than a terminal
operator, use [`plynth-sdk`](../sdks/python/) directly — don't depend
on `plynth_cli`.

## Quick examples

```bash
# Save platform admin token (talks to /api/v1/admin/*).
plynth login --admin-token "$PLATFORM_ADMIN_TOKEN"

# Bootstrap a new product with seeded standard plans.
plynth products create --slug chatbot --name "ChatBot" --tenant-type company

# List tenants and users inside chatbot.
plynth tenants list --product chatbot
plynth users list  --product chatbot --tenant acme

# Invite a new user under the 'acme' tenant of 'chatbot'.
plynth users invite --product chatbot --tenant acme --email alice@example.com

# Grant feature credits.
plynth credits grant \
  --product chatbot --tenant acme \
  --feature ai_completion --amount 1000

# Inspect the current subscription.
plynth subscription show --product chatbot --tenant acme

# Recent audit / ledger activity (falls back to credit ledger
# until /api/v1/audit ships — see docs/architecture.md § 6).
plynth audit list --product chatbot --tenant acme --limit 50
```

## Auth modes

Two modes; pick one based on what you need to do.

### 1. Platform-admin token (god-mode)

Required for `/api/v1/admin/*` (product CRUD) and convenient for any
cross-product admin work. The token is read from the
`PLATFORM_ADMIN_TOKEN` server env — ask your operator for it.

```bash
plynth login --admin-token "$PLATFORM_ADMIN_TOKEN"

# Optional: pick a default product slug so non-/admin endpoints
# (tenants, users, plans, credits) also work under the same token.
plynth login --admin-token "$PLATFORM_ADMIN_TOKEN" \
             --admin-product chatbot
```

The token is sent as `X-Platform-Admin-Token`. The CLI auto-picks the
admin token for paths under `/api/v1/admin/`, and falls back to it for
any other path when no user session is saved (admin god-mode).

### 2. Email / password (per-user JWT)

```bash
plynth login --product chatbot --email alice@example.com
# password prompted, hidden
```

`POST /auth/login` returns `{access_token, refresh_token, expires_at}`;
both tokens are persisted (chmod 600). On any 401 the CLI silently calls
`/auth/refresh` once and retries the original request.

`plynth logout` revokes the refresh token server-side and clears the
local session. Add `--admin` to also wipe the saved platform-admin token.

### Inspect state

```bash
plynth auth whoami   # local config / session (no API call)
plynth auth me       # GET /auth/me — server's view + permission codes
```

## Output formats

* Default: a `rich` table (or pipe-delimited if `rich` isn't installed).
* `--json` on any list/show/create command: raw JSON.

Errors are caught centrally. The API's error envelope
(`{code, message, details}`) is printed as `code: message` in red and the
CLI exits with status `1`.

## Config file

Path: `${XDG_CONFIG_HOME:-~/.config}/plynth/config.json`. Permissions
forced to `0600`. Shape:

```json
{
  "base_url": "http://localhost:8000",
  "session": {
    "access_token":  "...",
    "refresh_token": "...",
    "expires_at":    "2026-05-21T12:34:56Z",
    "product_slug":  "chatbot",
    "email":         "alice@example.com"
  },
  "admin_token":         null,
  "admin_product_slug":  null,
  "acting_tenant_slug":  null
}
```

### Per-call overrides

All three CLI globals can be set as flags **or** env vars:

| Flag                     | Env var                       | Effect                                                  |
| ------------------------ | ----------------------------- | ------------------------------------------------------- |
| `--base-url URL`         | `PLYNTH_BASE_URL`             | Target a different server (staging, prod, local).       |
| `--product-slug SLUG`    | `PLYNTH_PRODUCT_SLUG`         | Override the session product (sent as `X-Product-Slug`).|
| `--acting-tenant-slug S` | `PLYNTH_ACTING_TENANT_SLUG`   | Act-as a child tenant (`X-Acting-Tenant-Slug`).         |

Many subcommands also have per-call `--product` / `--tenant` flags for
the same purpose without exporting an env var.

## Command catalogue

| Group           | Commands                                                            |
| --------------- | ------------------------------------------------------------------- |
| `auth`          | `login`, `logout`, `me`, `whoami`                                   |
| `products`      | `list`, `create`, `update`                                          |
| `tenants`       | `list`, `create`, `activate`, `deactivate`, `expire`                |
| `users`         | `list`, `invite`, `activate`, `deactivate`, `delete`                |
| `plans`         | `list`, `create`, `update`                                          |
| `subscription`  | `show`, `purchase`, `change`, `cancel`                              |
| `credits`       | `wallets`, `ledger`, `grant`                                        |
| `audit`         | `list` (falls back to `/credits/ledger` until `/audit` ships)       |

Use `plynth <group> --help` and `plynth <group> <cmd> --help` for full
flag listings.
