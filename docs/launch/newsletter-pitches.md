# Plynth — Developer Newsletter Outreach Package

Plynth is an open-source multi-tenant multi-product SaaS backend scaffold
(FastAPI + async SQLAlchemy + Postgres). This document is the playbook
for getting it covered in developer newsletters.

- Repo: https://github.com/shubhamkatta/plynth
- Docs: https://shubhamkatta.github.io/plynth/
- License: MIT
- Author: Shubham Katta (shubhamkatta7@gmail.com)

---

## 1. Newsletter target list

| # | Newsletter | URL | Submission path | Audience | Why it fits | Section |
|---|---|---|---|---|---|---|
| 1 | Console.dev | https://console.dev | https://console.dev/about/ (submit form) | ~70k devs, open-source tool curators | Plynth is exactly their format: an OSS tool with a clear use case | Tool of the week |
| 2 | Python Weekly | https://www.pythonweekly.com | rahul@pythonweekly.com | ~100k Python devs | Real-world async FastAPI + SQLAlchemy scaffold | Projects / Interesting Projects |
| 3 | PyCoder's Weekly | https://pycoders.com | https://pycoders.com/submissions | ~120k Python devs | Production-grade Python architecture example | Projects & Code |
| 4 | Real Python newsletter | https://realpython.com/newsletter/ | info@realpython.com | ~300k Python learners | Concrete reference implementation of a SaaS backend | Community / Projects |
| 5 | TLDR Webdev | https://tldr.tech/webdev | https://tldr.tech/signup (submit at bottom) | ~1M+ across TLDR family | Multi-tenant SaaS plumbing is a frequent backend topic | Quick links / Open source |
| 6 | Awesome Python Newsletter | https://python.libhunt.com | https://python.libhunt.com/newsletter | ~30k Python devs | Curates libraries and scaffolds | Featured project |
| 7 | SaaSHub Weekly | https://www.saashub.com | https://www.saashub.com/submit-product | SaaS builders / indie hackers | Direct match — they cover SaaS tooling | Open source / Dev tools |
| 8 | DB Weekly | https://dbweekly.com | peter@cooperpress.com | ~30k DB-curious devs | Tenant-isolation + partial unique indexes are DB-design content | Articles / Tools |
| 9 | Postgres Weekly | https://postgresweekly.com | peter@cooperpress.com | ~40k Postgres devs | Multi-tenant schema patterns + RLS-adjacent design | Articles / Tools |
| 10 | Hacker Newsletter | https://hackernewsletter.com | https://hackernewsletter.com/submit | ~80k HN readers | Curates from HN — pitch after a Show HN gets traction | Projects |
| 11 | Changelog Weekly | https://changelog.com/weekly | editors@changelog.com | ~70k OSS-focused devs | OSS launches are their core beat | Open source |
| 12 | Bytes.dev | https://bytes.dev | Skip — JS-only, low fit | ~200k JS devs | Only worth it if a Next.js starter post is published separately | n/a |

---

## 2. Generic pitch email template

**Subject:** Plynth — open-source multi-tenant multi-product SaaS backend (FastAPI)

**Body:**

Hi {{editor_name}},

I built Plynth, an MIT-licensed FastAPI + async SQLAlchemy scaffold that
gives you the parts every SaaS backend re-implements: JWT auth, RBAC,
multi-tenant isolation, billing (Stripe-pluggable), credits ledger,
jobs, storage, webhooks, plus an Electron admin and a Next.js starter.

What makes it different: most scaffolds are single-product. Plynth runs
many independent products on one deployment with strict
product + tenant isolation enforced at the repository layer.

Your {{newsletter_name}} readers might care because:

- It removes 2-3 months of platform plumbing from a new SaaS project.
- The architecture doc (HLD + LLD + route catalogue) is published so
  readers can evaluate the design before installing anything.

Links:
- Repo: https://github.com/shubhamkatta/plynth
- Docs: https://shubhamkatta.github.io/plynth/
- License: MIT

Happy to answer questions or send a one-paragraph blurb in your house
style if helpful.

Thanks,
Shubham Katta

---

## 3. Tailored variants

### 3a. Console.dev

**Subject:** Plynth — open-source SaaS backend scaffold for your tool roundup

Hi Console team,

Plynth is an MIT-licensed FastAPI scaffold that ships the boring,
required parts of a SaaS backend: auth, RBAC, multi-tenant + multi-product
isolation, billing, credits, jobs, storage, webhooks, and an Electron
admin client. It is designed for solo founders and small teams who want
to skip 2-3 months of platform work and start on product code on day one.

It fits Console's tool-of-the-week format: one repo, one clear purpose,
production-shaped architecture, full docs (HLD + LLD + route catalogue
at https://shubhamkatta.github.io/plynth/), reproducible quickstart.

- Repo: https://github.com/shubhamkatta/plynth
- License: MIT

Shubham Katta

### 3b. Python Weekly

**Subject:** Plynth — async FastAPI + SQLAlchemy multi-tenant SaaS scaffold

Hi Rahul,

Sharing Plynth for possible inclusion. It is an MIT-licensed
production-shaped Python backend: FastAPI, async SQLAlchemy 2.x,
Postgres, Redis, arq workers. Strict layering (api -> service ->
repository -> model), one transaction per request, typed exceptions,
structured logging, audit on every mutation.

Python-specific things readers may find useful: a working pattern for
multi-tenant + multi-product row scoping via a `TenantRepository` base
class, async billing webhook handling with idempotency keys, and a
credits ledger using `SELECT ... FOR UPDATE`.

- Repo: https://github.com/shubhamkatta/plynth
- Docs: https://shubhamkatta.github.io/plynth/

Shubham Katta

### 3c. Postgres Weekly

**Subject:** Multi-tenant + multi-product Postgres schema patterns (open-source reference)

Hi Peter,

Plynth is an open-source FastAPI backend whose interesting half is its
Postgres schema. Every domain table carries `product_id` and
`tenant_id`; all reads/writes route through a repository that enforces
the dual filter; cross-scope access requires an explicit
`with bypass_*()` block that is auditable via grep.

It also demonstrates partial unique indexes for per-tenant uniqueness,
append-only ledgers for credits, and Alembic migration patterns for
adding tenant scoping to existing tables.

The schema and isolation rules are documented at
https://shubhamkatta.github.io/plynth/multi-tenancy/ and
https://shubhamkatta.github.io/plynth/multi-product/.

- Repo: https://github.com/shubhamkatta/plynth (MIT)

Shubham Katta

---

## 4. Outreach tracking table

| Newsletter | Submission URL / Email | Date Submitted | Status | Notes |
|---|---|---|---|---|
| Console.dev | https://console.dev/about/ |  |  |  |
| Python Weekly | rahul@pythonweekly.com |  |  |  |
| PyCoder's Weekly | https://pycoders.com/submissions |  |  |  |
| Real Python | info@realpython.com |  |  |  |
| TLDR Webdev | https://tldr.tech/signup |  |  |  |
| Awesome Python Newsletter | https://python.libhunt.com/newsletter |  |  |  |
| SaaSHub Weekly | https://www.saashub.com/submit-product |  |  |  |
| DB Weekly | peter@cooperpress.com |  |  |  |
| Postgres Weekly | peter@cooperpress.com |  |  |  |
| Hacker Newsletter | https://hackernewsletter.com/submit |  |  |  |
| Changelog Weekly | editors@changelog.com |  |  |  |

---

## 5. Timing & cadence

Submit Sunday evening or Monday morning UTC — most weekly newsletters
finalize Tuesday and ship Wednesday/Thursday. Wait 10-14 days before a
single polite follow-up. Stagger submissions over 5-7 days rather than
blasting on one day; this lets you tune the pitch based on early
responses and avoids overlapping issues if two newsletters bite the same
week.

---

## 6. What NOT to do

- Do not mass-CC editors on a single email; each pitch goes 1:1.
- Do not follow up more than once. Silence is a no.
- Do not pitch newsletters the same week as a Show HN — let HN
  momentum surface organically first, then pitch with the HN link as
  proof of interest the following week.
- Do not pitch the same editor (Peter Cooper runs both DB Weekly and
  Postgres Weekly) twice in the same week. Stagger or combine.
- Do not attach files. Links only.
- Do not pitch without first confirming the newsletter is actively
  publishing (check the last issue date).
