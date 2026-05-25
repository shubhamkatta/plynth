# Contributing to Plynth

Thanks for stopping by. **Plynth** is a drop-in multi-tenant, multi-product
SaaS backend scaffold — auth, RBAC, billing, credits, audit, and a reference
Electron admin client, all ready to host many independent products on a
single deployment. It exists so you don't have to rebuild the same platform
layer for every new SaaS idea.

First-time contributors are very welcome. Meaningful contributions span:

- **New features** — new vertical slices, new platform capabilities.
- **Docs** — clarifying `docs/ARCHITECTURE.md`, runbooks, integration guides.
- **Tests** — closing coverage gaps, especially cross-product / cross-tenant
  isolation tests.
- **Bug fixes** — including the boring ones.
- **Deploy recipes** — Fly.io, Render, Hetzner, bare-metal Caddy, etc.
- **Integrations** — new billing providers, notification providers, identity
  providers, storage backends.

If you're not sure whether something fits, open a `question` issue or a
discussion before sinking time into a big PR.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md).
By participating you agree to uphold it.

## Getting started

### Fork + clone

```bash
git clone git@github.com:<your-username>/plynth.git
cd plynth
git remote add upstream git@github.com:shubhamkatta/plynth.git
```

### Local dev

The whole stack runs in docker-compose (Postgres, Redis, the API, the
arq worker):

```bash
cp .env.example .env
make up           # docker compose up -d
make migrate      # apply alembic migrations
make seed         # default product + plans + admin user
open http://localhost:8000/docs   # OpenAPI / Swagger UI (non-prod only)
```

In production the OpenAPI schema is hidden by default
(`EXPOSE_OPENAPI=false`); locally it stays on so you can explore the
surface.

### Run the test suite

```bash
make test         # pytest, with the docker stack already up
```

### Lint & typecheck

```bash
make lint         # ruff
make typecheck    # mypy
```

All three (`make lint && make typecheck && make test`) must be green
before you open a PR.

### Electron admin client (optional)

The reference desktop admin lives under `apps/admin-electron/`. If your
change touches a platform endpoint that the admin surfaces, you'll want
to run it too:

```bash
cd apps/admin-electron
npm install
npm run dev
```

See `apps/admin-electron/README.md` for the IPC + bridge wiring rules.

## Project layout

- `app/` — the FastAPI service. Layers flow downward:
  `api → services → repositories → models`. Routers are dumb adapters;
  business logic lives in services.
- `docs/` — **source of truth**. Start at `docs/ARCHITECTURE.md` (HLD +
  LLD + every contract). Focused docs (`multi-tenant.md`,
  `multi-product.md`, `billing.md`, etc.) cross-link from there.
- `tests/` — pytest suite. Integration tests use a real Postgres via the
  same docker-compose stack.
- `apps/admin-electron/` — reference Electron desktop client. Consumes
  only the documented REST API.
- `scripts/` — operational scripts (password rotation, seed helpers,
  etc.). Stdlib-only where possible.
- `migrations/` — Alembic migrations. One per schema change, reversible
  by default.

If you only read one file before starting work, read
`docs/ARCHITECTURE.md`.

## Doc-as-source-of-truth contract

This is non-negotiable and copied verbatim from the in-repo `CLAUDE.md`:

> **`docs/ARCHITECTURE.md` is the source of truth** for this codebase. It
> contains HLD + LLD + every documented contract: data model, service
> boundaries, route catalogue, RBAC codes, configuration matrix, and the
> designed-but-not-yet-implemented **Jobs API** (§ 6.2) + **Storage API**
> (§ 6.3) that the Electron UI calls.
>
> **Workflow for every task in this repo:**
>
> 1. **Read** the relevant section of `docs/ARCHITECTURE.md` (and any
>    focused doc it cross-links) **before** designing the change.
> 2. **Implement** the change.
> 3. **Update the docs in the same commit** if your change touches any
>    contract. Use the touchpoint table in
>    `docs/ARCHITECTURE.md` § 8 — every code change that lands on a row
>    in that table edits both `ARCHITECTURE.md` AND the focused doc named
>    there.
> 4. **Tests** must pass before merging.
>
> If a contract changes (new column, new route, new permission code, new
> config key, new job type, new storage collection, new flow step):
> - Update `docs/ARCHITECTURE.md` first → confirm the design.
> - Implement to match.
> - Never ship code that diverges from the doc silently.
>
> If you implement a designed-but-not-implemented section (Jobs / Storage),
> mark it **"implemented"** at the top of that section in
> `docs/ARCHITECTURE.md` with a link to the PR.

In short: **every PR that touches a contract — a route, a column, a
permission, a config key, a job type, a storage collection, a flow step —
updates `docs/ARCHITECTURE.md` in the same commit.** A reviewer who
spots code that diverges from the docs will block the PR.

## Branching & commits

### Branches

Branch from `main`. Naming:

- `feat/<short-slug>` — new feature.
- `fix/<short-slug>` — bug fix.
- `docs/<short-slug>` — docs-only change.
- `chore/<short-slug>` — tooling, deps, CI, formatting.
- `sec/<short-slug>` — security fixes (still go through normal review;
  see `SECURITY.md` for private disclosure of vulnerabilities).

### Commit messages

Follow the Conventional Commits-ish pattern already visible in
`git log`:

```
feat(auth): per-product refresh-token TTL override
fix(subscription): purchase upserts — works on tenants with no prior sub
docs(architecture): document Jobs API contract
chore(gitignore): block *.pem / *.key / certs/ from ever being committed
sec: hide /docs + /openapi.json in production by default
```

Subject line is short, lowercase, no trailing period. The body (one or
two short paragraphs) explains the **why** — the diff already shows the
what. Reference issues with `Fixes #123` or `Refs #123`.

Keep commits atomic. A "fix the linter + rename a column + add a
feature" commit is hard to review and harder to revert. Split it.

## Pull request checklist

Before you click "Create pull request", confirm:

- [ ] `make lint && make typecheck && make test` all pass locally.
- [ ] New routes are guarded by permission dependencies
      (`Depends(require_permission("..."))`) **and** product context
      (`RequireProduct` for public routes, JWT `pid` for authenticated).
- [ ] New product/tenant-scoped queries go through `TenantRepository` /
      the filter mixins — they don't bypass the repository.
- [ ] Any `with bypass_product():` / `with bypass_tenant():` usage is
      called out in the PR description.
- [ ] New Alembic migration is reversible (`downgrade()` implemented), or
      explicitly marked forward-only with a reason in the migration
      docstring.
- [ ] Audit log entry is emitted for every state change
      (`audit.record(...)` / `audit.audit_action(...)`).
- [ ] No bare `except Exception`. No secrets in logs or in the audit
      `diff` payload.
- [ ] At least one cross-product / cross-tenant isolation test exists for
      any new surface.
- [ ] `docs/ARCHITECTURE.md` is updated if any contract changed (route,
      column, permission, config key, job type, storage collection, flow
      step).
- [ ] PR description explains the change and links any related issue.

CI will re-run lint / typecheck / tests. Reviewers will read the PR
description, the diff, and — for any contract change — the docs diff.



## Type hygiene (mypy)

`make typecheck` is run in CI but is **advisory** for now — the
pre-1.0 codebase has known type-annotation gaps we're chipping away
at. PRs that **don't introduce new mypy errors** are happily merged.
PRs that fix existing ones are doubly welcome. The plan is to flip
mypy to gating once `make typecheck` is clean.

Tightening sequence we're following:
1. Annotate every new function with arg + return types.
2. Resolve `Subscription | None` union-attr warnings as we touch each service.
3. Lift `check_untyped_defs` back on once the count is < 5 errors.
4. Restore `strict = true` in `pyproject.toml`.

## Reporting bugs / requesting features

Use the issue templates under
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/):

- **Bug report** — reproduction steps, expected vs actual, environment.
- **Feature request** — problem first, then proposed solution.

The more concrete the report, the faster it gets triaged.

## Security disclosures

**Do not file public GitHub issues for security vulnerabilities.** Follow
the private disclosure process in [`SECURITY.md`](SECURITY.md) instead.

## Need help / have questions?

- Open an issue with the `question` label.
- Or start a thread on GitHub Discussions (discussions will be enabled
  on the repo).

Either is fine. If your question turns out to be a doc gap, a docs PR
is the perfect outcome.

Thanks for contributing to Plynth.
