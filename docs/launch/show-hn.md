# Show HN draft — Plynth

> Use this when you're ready to launch. Submit to https://news.ycombinator.com/submit
> Best windows: Tuesday-Thursday, 9:00-10:00 AM ET (1:00-2:00 PM UTC).
> Pre-submit checklist at the bottom.

## Title (≤80 chars; HN allows 80)

**Suggested:**

  Show HN: Plynth – drop-in multi-product SaaS scaffold (FastAPI)

**Alternates** (pick the angle that resonates most for you):

  Show HN: Plynth – host many independent SaaS products on one Postgres
  Show HN: Plynth – the boring 80% every SaaS needs, in one repo
  Show HN: Plynth – I rebuilt the same SaaS plumbing 4 times, then made this
  Show HN: Stop rebuilding the same SaaS plumbing (Plynth, FastAPI + MIT)

## URL

  https://github.com/shubhamkatta/plynth

(Use the repo URL, NOT the docs site. HN moderators have stronger preference for source repos for Show HN.)

## First comment (post this immediately after the submission; it appears at the top)

Hi HN — I'm Shubham. Over the last two years I've shipped a handful of small SaaS products as a solo founder, and every single one started with me re-writing the same plumbing: signup, password reset, Google OAuth, an RBAC layer that wasn't a footgun, Stripe webhooks, a credits ledger, an audit trail I could actually grep, a worker queue, an admin UI. By product four I gave up and extracted the layer. Plynth is that layer.

Plynth is a FastAPI + async SQLAlchemy + Postgres + Redis backend scaffold under MIT. It's opinionated about one thing most scaffolds aren't: a single deployment hosts MANY independent SaaS products. Every domain row carries `(product_id, tenant_id)`, every query goes through a repository that enforces both filters, and cross-product or cross-tenant access requires an explicit `with bypass_product():` block that reviewers can grep for. That means I can run three SaaS apps off one Postgres without worrying that a bug in product A leaks into product B's customer data.

What's in the box today:

- Email + password auth, Google OAuth, forgot-password, JWT with a `pid` (product) claim.
- Per-product RBAC with `resource:action` permission codes and system roles seeded on product creation.
- Plans + subscriptions with a state machine (trial → active → past_due → grace → suspended → cancelled), provider-agnostic billing driver (Stripe stub included).
- Atomic credits wallet + append-only ledger (`SELECT … FOR UPDATE` + idempotency `reference`).
- Audit log on every state change, structured logging via structlog, typed `AppError` hierarchy.
- arq-based job queue and a reference Electron admin app that talks only to the documented REST surface.

What it's NOT: it isn't a frontend (build your own), it isn't an email sender (provider stub — bring SES/Resend/Postmark), and it isn't a hosted SaaS. You run it.

Three things I'd genuinely love feedback on:

1. Is `(product_id, tenant_id)` the right primitive, or am I conflating two concerns that should stay separate? Architecture rationale is in https://shubhamkatta.github.io/plynth/architecture/ § 3.
2. The subscription state machine (trial → active → past_due → grace → suspended → cancelled) — does this match how people who've actually shipped billing model the lifecycle? I've been burned by skipping the `grace` state before.
3. Anything in the API surface that feels weird or non-idiomatic? OpenAPI spec is at https://shubhamkatta.github.io/plynth/api-reference/.

Honest comparison so you don't have to dig: vs Supabase/Nhost, those are wonderful if you want managed infra and one product per project — you write less ops, but you own less of your data plane and multi-product on one deploy isn't really their shape. vs rolling your own, DIY is faster for the first week and slower forever after; Plynth trades a couple of days of learning the conventions for not re-writing audit + RBAC + billing-state on product five. vs Django + django-tenants, Django is more batteries-included on the frontend/admin side, Plynth is async-native FastAPI with a stricter product/tenant isolation contract.

Happy to answer anything about the architecture, the RBAC model, billing state edges, or why I picked arq over Celery in this thread. Live docs and demo at https://shubhamkatta.github.io/plynth.

## Pre-submit checklist

Before clicking submit:

- [ ] README opens with the clear value prop in the first 3 sentences (it does)
- [ ] Demo / docs link is one click away from README (it is — banner badge points to shubhamkatta.github.io/plynth)
- [ ] At least one issue with `good first issue` label exists (we have 10)
- [ ] License is on the README + LICENSE file (MIT, both present)
- [ ] Quickstart on the README is genuinely 5 minutes (verify on a fresh clone before submitting)
- [ ] You're free for the next 4-6 hours after submit to respond to every comment in <30 min
- [ ] You have something to say to negative comments (don't argue; acknowledge, point to alternative, learn)

## After submit

- Don't ask friends to upvote (banned, detectable, kills the post)
- Reply to EVERY comment within 30 min for the first 4 hours
- If a comment is critical, lead with "good point" → engage with the substance → say what you'll do about it
- After 24h: post a follow-up update in GitHub Discussions linking the HN thread + summarizing what you learned

## What good looks like

A successful Show HN for a project of this category lands ~300-500 stars in 48h if it hits the front page. Don't reset expectations daily — check at 24h and 7d marks.
