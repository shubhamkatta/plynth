# Twitter/X launch thread

> Post the day of your Show HN. Schedule for ~30 min after the HN submission so you have a single moment of attention to direct.
>
> 280 chars per tweet (some are 4000 for X Premium — write for 280 to be safe).
>
> The tweets are numbered. Post tweet 1 as a standalone, then reply to it with tweet 2, then reply to 2 with 3, etc. (Don't use a thread-tool — manual replies index better.)

## Thread (10 tweets)

### 1/10  (the hook)

```
Every founder rebuilds the same 6 months of SaaS plumbing before writing a line of product code.

Auth. Tenants. RBAC. Plans. Credits. Audit. Jobs.

I made Plynth so you don't.

MIT. FastAPI. Multi-product on one deploy.

github.com/shubhamkatta/plynth

🧵
```

_Attach: `docs/assets/banner-dark.svg` (export to PNG — Twitter prefers raster)._

### 2/10  (the pain)

```
Boring stuff every SaaS rebuilds:

— Auth + JWT + Google OAuth + reset
— Multi-tenant isolation
— RBAC with per-product roles
— Plans + subscription state machine
— Credits ledger
— Audit on every mutation
— Background jobs

80% of the work. None of it your product.
```

### 3/10  (the differentiator)

```
Plynth's wedge: one deployment hosts MANY independent products.

Most scaffolds = one product per deploy.
Plynth = N products on one Postgres, each with its own tenants, plans, RBAC.

Every domain row keys on (product_id, tenant_id). Dual-filtered at the repo layer.
```

_Optional second tweet (3a) with the code snippet, posted as a reply between 3 and 4 if you want — or inline as alt text:_

```python
# Every table keys off (product_id, tenant_id)
class Subscription(ProductScopedMixin, TenantScopedMixin, Base):
    ...
```

### 4/10  (what's in the box)

```
What ships in the box:

FastAPI + SQLAlchemy 2.0 async + Postgres 16 + Redis 7 + arq jobs.

Identity, RBAC, plans, subs, credits ledger, audit, jobs, Electron admin.

200+ tests. mypy strict. 88% coverage. MIT.

Full comparison vs Supabase / Nhost / PocketBase in the README ↓
```

_Attach: screenshot of the "Compared to alternatives" table from the README._

### 5/10  (quickstart)

```
5 minutes from zero to a running SaaS backend:

  git clone github.com/shubhamkatta/plynth
  cd plynth
  make up
  make seed

Then open http://localhost:8000/docs.

You now have: a product, a tenant, an admin user, a trial subscription, and 50 routes ready to call.
```

_Attach: terminal screenshot of the four commands._

### 6/10  (Electron admin)

```
It also ships an Electron admin app.

One desktop window to manage every product, tenant, user, role, plan, subscription, credit wallet, and audit row across the whole deployment.

No privileged backdoor — same REST API your customers use. Just a nicer CRUD shell.
```

_Attach: screenshot of the Electron admin, ideally the Tenants page._

### 7/10  (architecture)

```
Architecture in one line:

one FastAPI process • many isolated products • one Postgres • one Redis.

Layers flow down: api → services → repos → models.
Routers are dumb adapters. One transaction per request. All async.

Docs: shubhamkatta.github.io/plynth
```

_Attach: screenshot of the Mermaid architecture diagram from the docs site._

### 8/10  (comparison — honest)

```
Honest positioning:

— Supabase: best if you want BaaS + a hosted dashboard.
— Nhost: best if you want GraphQL-first.
— PocketBase: best if you want a single Go binary.
— Plynth: best if you want Python + multi-product on one deploy, and you want to own the code.
```

### 9/10  (CTAs)

```
If this looks useful:

⭐ Star — github.com/shubhamkatta/plynth
📚 Docs — shubhamkatta.github.io/plynth
💬 Discussions — ideas, questions, "does it do X?"

The roadmap, ADRs, and full architecture HLD + LLD all live in /docs.
```

### 10/10  (close + ask)

```
Real question for the replies:

what is the single most painful piece of SaaS plumbing you've rebuilt across projects? I'll feed answers straight into the v0.2 roadmap.

Solo-maintaining this — would love help on the `help wanted` issues.

— @shubhamkatta
```

## Asset references (you'll attach these to specific tweets)

- Tweet 1: `docs/assets/banner-dark.svg` (or .png export — Twitter prefers raster)
- Tweet 4: screenshot of the "Compared to alternatives" README table
- Tweet 5: terminal screenshot of the quickstart commands
- Tweet 6: screenshot of the Electron admin (e.g. Tenants page)
- Tweet 7: screenshot of the Mermaid architecture diagram

## Posting checklist

- [ ] Pre-write all 10 tweets in this doc; copy-paste sequentially (don't write live)
- [ ] Have all images ready in a folder before starting
- [ ] First reply (tweet 2) within 1 minute of tweet 1 so the thread doesn't fragment
- [ ] Quote-RT the thread from a second account / mutuals after 2 hours to boost reach
- [ ] After 24h, post a follow-up thread with "what happened" + key feedback

## Variant: short LinkedIn-ish post (for crossposting)

A single-post version (no thread) for LinkedIn / Bluesky / Mastodon. Same hook, condensed to three short paragraphs:

```
Every founder rebuilds the same six months of SaaS plumbing before writing a line of product code — auth, multi-tenancy, RBAC, plans, credits, audit, jobs. It's 80% of the work and none of it is your product.

I shipped Plynth to skip it. Python + FastAPI + Postgres + Redis. Multi-tenant AND multi-product: one deployment hosts many independent SaaS products, each with its own tenants, plans, and RBAC, all keyed on (product_id, tenant_id). 200+ tests, mypy strict, 88% coverage, MIT.

Five minutes from `git clone` to a running backend with a product, a tenant, an admin user, and a trial subscription. Star, fork, break it: github.com/shubhamkatta/plynth — docs at shubhamkatta.github.io/plynth.

— @shubhamkatta
```
