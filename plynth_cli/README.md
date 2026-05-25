# plynth_cli

Terminal-first admin/ops client for the [Plynth](../README.md) multi-tenant
SaaS platform. Mirrors the surface area of `apps/admin-electron/` for
shell users — every operation goes through the documented public REST
API (`/api/v1/*`); no privileged surface.

## Install

The CLI lives alongside the main Plynth Python package. A normal editable
install of the platform pulls `httpx` (already a production dep) into
your environment; you also need `click`:

```bash
pip install -e .
pip install "click>=8.0"  # not in core deps yet
pip install rich          # optional — pretty tables; degrades gracefully
```

> When a maintainer is ready to make the CLI a first-class entrypoint,
> add the following to `pyproject.toml` (omitted from this PR to avoid
> conflicts with concurrent agents):
>
> ```toml
> dependencies = [
>   # …existing…
>   "click>=8.0",
>   "rich>=13.0",   # optional but recommended
> ]
>
> [project.scripts]
> plynth = "plynth_cli.cli:main"
> ```

Invoke via the module entrypoint:

```bash
python -m plynth_cli --help
```

You can also alias it for convenience:

```bash
alias plynth='python -m plynth_cli'
plynth --help
```

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
