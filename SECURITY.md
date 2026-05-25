# Security Policy

## Supported versions

Plynth is at v0.x. There's a single supported line — **`main`** — and
the recommended practice for production is to pin to a specific commit
SHA. Tagged releases will start at v1.0.

| Version | Supported          |
| ------- | ------------------ |
| `main`  | ✅                  |
| < v1.0  | Best-effort        |

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Use one of:

1. **GitHub Security Advisory** (preferred) —
   <https://github.com/shubhamkatta/plynth/security/advisories/new>.
   Encrypted in transit, auditable, lets us coordinate a fix + CVE.
2. **Email** — `shubhamkatta7@gmail.com`. Subject prefix `[plynth-sec]`
   helps us triage fast.

Include if you can:

- A description of the issue and the impact you observed.
- Steps to reproduce — ideally a minimal `curl` / script.
- Suspected severity (low / medium / high / critical).
- Whether you've disclosed it elsewhere.

## What to expect

- **Acknowledgement within 72 hours.**
- Triage + initial assessment within 7 days.
- Coordinated disclosure: a fix lands in `main`, an advisory + CVE is
  published, and reporters are credited (or kept anonymous if preferred).
- Target patch window: 30 days for high/critical, 90 days for medium/low.

## Scope

**In scope:**

- The platform API (`app/`) — auth, RBAC, multi-tenant isolation,
  billing/credits, audit, webhooks.
- The reference Electron admin (`apps/admin-electron/`) — IPC surface,
  preload bridge, keychain handling.
- Deploy configs in `docs/deploy-*.md`, `Dockerfile`, `docker-compose*.yml`,
  `Caddyfile.example`, `fly.toml`, `scripts/`.

**Out of scope (file with the upstream):**

- Third-party billing providers (Stripe, etc.) — report to them.
- Third-party identity providers (Google OAuth) — report to them.
- DNS / CDN provider issues (Cloudflare, etc.).
- Vulnerabilities in dependencies fixed by an upstream release — open
  a normal issue or a dependabot-style PR; we'll bump.

## Hardening guidance for operators

Plynth ships with sensible defaults but production hardening is on
you. The shortlist:

- **Rotate `PLATFORM_ADMIN_TOKEN` quarterly.** It's a true super-user;
  treat it like a root password.
- **Set `APP_ENV=production`** in your `.env`. This hides `/docs` and
  `/openapi.json` and tightens other defaults.
- **Keep `EXPOSE_OPENAPI` unset (or `false`)** in production unless you
  have a specific reason — the schema is free reconnaissance for
  attackers.
- **Terminate TLS at a hardened reverse proxy** (Caddy + Cloudflare, or
  Fly's edge). The app speaks plain HTTP behind it.
- **Restrict SSH** on your deploy host (key-only, known IPs, fail2ban).
  See `docs/deploy-digitalocean.md` for a worked example.
- **Don't commit `.env`.** The repo's `.gitignore` blocks it; verify
  before pushing.
- **Run `make test` in CI** for every PR — RBAC and isolation
  regressions are the easiest to introduce.

## Crediting

Researchers who disclose responsibly get credit in the published
advisory (and the release notes for the fix) unless they prefer to
stay anonymous. There's no bug-bounty program right now.
