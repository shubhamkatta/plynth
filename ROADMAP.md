# Roadmap

Plynth is a young project. This document is the public, plain-language
view of where it's heading. It is intentionally not a calendar — there
are no dates here. What you'll find instead is a relative ordering: what
is happening **Now**, what we'd like to start **Next**, what we'd love
help with **Later**, and what we've explicitly **parked**.

The goal of this page is to make it easy for anyone — a casual reader,
a potential contributor, or a team picking Plynth up for their own
product — to see whether something they care about is on the path.

If you want to influence what gets built, jump to the
[How to influence the roadmap](#how-to-influence-the-roadmap) section at
the bottom — it points at GitHub Discussions and the labels we use to
flag work that's open for first-time contributors and for sponsorable
mid-effort tasks.

---

## Now (in v0.1.x)

The current line of work is small, defensive, and aimed squarely at
keeping `main` healthy after the initial v0.1.0 release. No new
surfaces, no contract changes — just polish, dependency hygiene, and
fixing things that turn out to be wrong in the open.

- **Triage and merge the open Dependabot PRs** for GitHub Actions
  (`actions/checkout`, `actions/cache`, `actions/setup-python`,
  `actions/setup-node`) once each lands green CI. These are PRs
  [#1](https://github.com/shubhamkatta/plynth/pull/1) through
  [#4](https://github.com/shubhamkatta/plynth/pull/4).
- **Resolve the larger Dependabot bumps** flagged
  `needs-investigation` — Vite + electron-vite
  ([#11](https://github.com/shubhamkatta/plynth/pull/11)) and
  `eslint-plugin-react-hooks` v5 → v7
  ([#12](https://github.com/shubhamkatta/plynth/pull/12)) — both need
  the admin-electron build verified and migration notes captured before
  merge.
- **Onboarding polish** — small documentation patches in `docs/`, a
  `make new-product <slug>` convenience target, and short
  "Common errors and what they mean" / "How to add an RBAC permission"
  guides so new contributors don't have to grep the codebase to make a
  first change.
- **Regression coverage** — add tests for edge cases that exist in code
  but are not yet asserted (e.g. "a deleted role cannot be reassigned"),
  and a handful of `chore:` cleanups across the admin-electron renderer.
- **Tightening the type story** — continue chipping away at the mypy
  backlog called out in `CONTRIBUTING.md` § *Type hygiene*. Typecheck is
  advisory today; the v0.1.x line should leave it visibly closer to
  gating.

You can see the active list under the
[`good first issue`](https://github.com/shubhamkatta/plynth/labels/good%20first%20issue)
label.

---

## Next (v0.2)

The v0.2 line is about making Plynth genuinely complete for the
read-write product workloads people actually build on top of it. Most
of these items already have a designed contract in
[`docs/architecture.md`](docs/architecture.md) — the work is the
implementation, not the design.

- **Implement the Jobs API** (`architecture.md` § 6.2). The contract is
  written — typed handler registry, queue + status endpoints, arq
  worker integration, RBAC codes. Today the worker exists; the
  user-facing API does not. This unlocks long-running product work
  (PDF rendering, batch imports, scheduled exports) without each
  product reinventing the queue.
- **Implement the Storage API** (`architecture.md` § 6.3). Same shape:
  per-product `storage_kv` + `storage_blob_uploads`, scoped routes,
  permission codes (`storage:read`, `storage:write`, `storage:admin`).
  Even without an S3 driver it's useful as a Postgres-backed KV; the
  blob driver follows in v0.3.
- **Wire a real notification provider** behind
  `app/providers/notifications.py`. Today the module logs and returns.
  v0.2 should make forgot-password emails actually arrive — Resend or
  Postmark are the two drivers under consideration, both pluggable
  behind the same interface so production swaps are a config change.
- **Per-product webhooks endpoint** — admins register HMAC-signed
  delivery URLs against a product; the platform fans out subscription /
  user / credit events with retry + backoff. This is the missing piece
  for integrators who want to react to platform events without polling.
- **`plynth` CLI** — terminal-first ergonomics around the things that
  are curl + JWT today: bootstrap a product, mint an invite link,
  inspect audit, top up credits. Wraps the same REST API the Electron
  admin uses.
- **Frontend starter under `examples/`** — a Next.js app that talks to
  Plynth via the documented REST API, so newcomers can `git clone` and
  see a real login + tenant-switcher + dashboard within a minute. Not a
  framework lock-in; one of several future starters.
- **Flip mypy back to gating in CI** — finish the type-hygiene backlog
  and remove the "advisory" caveat from `CONTRIBUTING.md`.

---

## Later (v0.3+)

These are the bigger ideas — they need design, they often need a
sponsoring use case, and most are tagged `help wanted` so a motivated
contributor can take them on. Ordering here is rough.

- **Multi-region tenant routing.** Today Plynth assumes a single
  Postgres + Redis pair per deployment. A v0.3+ release should support
  routing a tenant to one of several regional shards via a thin
  resolver in front of `TenantRepository`, with per-region failover and
  read replicas. The hard part is the contract for cross-region
  reporting and audit fan-in.
- **Per-product feature flags + a light experiment framework.**
  `Product.settings` already carries config flags; the next step is a
  first-class `feature_flag` table, percentage rollouts, and a
  per-request evaluation cache. Experimentation (A/B) is a stretch goal
  on top of the same surface.
- **Object-storage driver for the Storage API.** Once § 6.3 lands as a
  Postgres-backed KV in v0.2, v0.3+ should add an S3 / R2 driver behind
  the same interface — presigned uploads, lifecycle rules,
  bring-your-own-bucket so customers can keep blobs in their own
  account.
- **Plugin / extension autoload.** The architecture already reserves
  `app/products/<name>/` for vertical product modules. A discovery
  mechanism (drop a folder in, restart, the platform mounts its
  routers + migrations + RBAC codes) would make Plynth genuinely
  pluggable rather than fork-and-extend.
- **SSO providers beyond Google.** Microsoft (Entra ID), Apple, and
  generic SAML 2.0. The Google flow in `app/services/auth.py` is the
  template — the work is mostly per-provider quirks and per-product
  auto-provisioning toggles, not new architecture.

---

## Maybe / not now

A roadmap is also about the things you've considered and decided
**not** to do — at least not soon. These are sincere "no for now"s, not
permanent rejections, but if you're hoping to see them next month, you
should know up front.

- **A hosted Plynth (cloud SaaS).** Plynth's value today is that you
  can run it yourself, on your own Postgres, with your own keys. We
  want self-host to be excellent before we split attention onto an
  operations org. We are not building a paid cloud tier in the v0.x
  line.
- **A built-in frontend SDK.** Plynth is a REST API and an admin
  Electron client. We'd rather let frameworks (Next.js, Remix, SvelteKit)
  compete on the client side than ship an opinionated JS SDK that ages
  badly. The `examples/` starters mentioned above are the
  compromise — copyable, not a dependency.
- **Per-product database-schema customisation.** Letting product A add
  a column to `users` that product B doesn't see would either break the
  multi-tenant guarantees or push us into per-product schemas, both of
  which we've explicitly decided against. Use `Product.settings` JSONB
  or your own product-scoped tables under `app/products/<name>/`
  instead.

---

## How to influence the roadmap

This roadmap is opinionated but not closed. If you want to push on it:

- **Propose new ideas on GitHub Discussions.** Open a thread under
  [Plynth Discussions](https://github.com/shubhamkatta/plynth/discussions)
  describing the problem you're trying to solve. We strongly prefer
  problem statements over solution requests — they're easier to
  generalise. Discussions is also where we collect "we keep meaning to
  do this" items before they become issues.
- **Pick up a `good first issue`.** The
  [`good first issue`](https://github.com/shubhamkatta/plynth/labels/good%20first%20issue)
  label tags small, well-scoped, ~1-2 hour tasks suitable for someone
  making their first PR. Every one of these has a "Where to start"
  pointer in the body.
- **Pick up a `help wanted` issue.** The
  [`help wanted`](https://github.com/shubhamkatta/plynth/labels/help%20wanted)
  label tags mid-effort work (typically half-day or more) that has a
  designed contract but is waiting on someone to implement it. Several
  of these correspond directly to the v0.2 and v0.3 items above.
- **Sponsor a v0.3+ item.** If your team needs one of the Later items
  on a real timeline, please open a Discussion and say so. Plynth is a
  small project; named demand is the most reliable way to move
  something forward.

If something you care about is missing entirely, open a Discussion —
the worst case is we add it here under *Maybe / not now* with our
reasoning, so you don't have to guess.
