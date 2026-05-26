# LinkedIn launch post

> Single long-form post, not a thread. Post 2-3 hours before/after Show HN to avoid splitting attention.
>
> Use the "Link in comments 👇" pattern — paste the repo + docs URLs as the first comment immediately after publishing.

## The post (paste this directly)

Most SaaS founders burn six months rebuilding the same backend before they write a single line of product code.

Auth, multi-tenancy with strict isolation, RBAC, plans, subscriptions, a billing state machine, metered credits, audit logs, background jobs, deploy story — boring, security-critical, and almost identical across every product you'll ever ship.

I just open-sourced the backend I wished existed every time I started a new company.

It's called Plynth. A reusable, MIT-licensed backend layer built on FastAPI, Postgres, Redis and arq. Fork it, drop your product code under app/products/<name>/, ship in a week instead of six months.

The differentiator: one deployment hosts many independent products. Every domain row is keyed on (product_id, tenant_id) and enforced at the repository layer, so you can run an internal tool, a B2C app, and a B2B platform on one Postgres and one worker pool with zero cross-bleed. The same email can sign up in two products without conflict. Add a new product with one admin call.

What's in the box:

→ Identity: email/password, JWT + refresh, Google OAuth, password reset
→ Multi-tenant + multi-product isolation enforced at the repository layer
→ RBAC with per-product roles and resource:action permissions
→ Provider-agnostic billing with a documented subscription state machine
→ Append-only credits ledger with atomic, idempotent debits
→ Audit log on every state-changing call, structured logs everywhere
→ Background jobs, Alembic migrations, Docker compose, Fly + DO deploy guides
→ A reference Electron admin console that consumes only the public REST API

Who it's for:

Founders building multiple SaaS products on shared infrastructure. Engineering teams that want full ownership of identity and billing instead of renting them. Indie hackers who'd rather spend the first month on the product, not the plumbing.

MIT licensed, batteries-included, demo and docs in the first comment. Stars and feedback genuinely help me decide what to ship next in v0.2.

#opensource #saas #fastapi #softwarearchitecture #startups

## The first comment (paste this immediately after publishing)

Demo + 5-min quickstart: https://shubhamkatta.github.io/plynth/
Source: https://github.com/shubhamkatta/plynth
Roadmap input wanted (v0.2): https://github.com/shubhamkatta/plynth/discussions

If you've built or shipped multi-tenant SaaS, I'd love to hear what we got right and wrong — the design decisions in docs/ARCHITECTURE.md are the part I most want pressure-tested.

## Variant: a shorter 600-char version

Most SaaS founders rebuild six months of identity, tenancy, RBAC, billing, credits, audit and jobs before they write any product code.

I open-sourced the backend I wished existed every time I started a new company.

Plynth: MIT, FastAPI + Postgres + Redis. One deployment hosts many independent SaaS products, each with its own tenants, plans and billing — isolation enforced at the repository layer. Fork it, drop your product in, ship in a week.

Link in comments 👇

#opensource #saas #fastapi #startups

## Post-publish playbook

- [ ] Add the link comment within 60 seconds (LinkedIn boosts posts with early engagement)
- [ ] DM 5-10 trusted contacts asking them to add a thoughtful comment (NOT a like — comments boost reach 10×)
- [ ] Engage with every comment within 30 min for the first 2 hours
- [ ] Re-share to 1-2 relevant LinkedIn groups (SaaS Founders, Indie Hackers on LinkedIn, etc.)
- [ ] If a comment is critical, lead with "good point" — never argue
