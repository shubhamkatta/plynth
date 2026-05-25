# 🏛️ Plynth

**Stop rebuilding the same SaaS plumbing.** Plynth is a drop-in,
batteries-included backend scaffold for multi-tenant, multi-product
SaaS — auth, RBAC, billing, credits, audit, and a reference Electron
admin client, all wired together and ready to ship.

Most SaaS backends start with the same six weeks of boilerplate: tenant
modelling, password hashing, JWT plumbing, role-based access, Stripe
webhooks, an audit log, a usage meter. Plynth treats that layer as a
solved problem so you can spend day one on your actual product. Auth,
billing, credits, and audit are an independent **platform layer**; each
real product you ship lives on top under `app/products/<name>/` and
inherits all of it for free.

The scaffold is opinionated about the things that are painful to change
later — every domain table is scoped on `(product_id, tenant_id)`, every
mutating route is gated by a permission code, and every state change
writes an audit entry — and unopinionated about the things you should
keep open, like your billing provider, your storage backend, and your
frontend stack. What's shipped today: FastAPI + async SQLAlchemy +
PostgreSQL + Redis + arq, a pluggable Stripe driver, an Argon2id auth
flow, B2B and B2C signup paths, a 170+ test suite, and an Electron 32
reference admin client.

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Get started in 5 min**

    ---

    Clone the repo, boot the stack, seed the default product, and make
    your first authenticated call.

    [:octicons-arrow-right-24: Quickstart](quickstart.md)

-   :material-sitemap:{ .lg .middle } **Architecture & contracts**

    ---

    HLD + LLD, data model, route catalogue, RBAC codes, configuration
    matrix, and the Jobs / Storage API contracts.

    [:octicons-arrow-right-24: Architecture](architecture.md)

-   :material-puzzle:{ .lg .middle } **Integration guide**

    ---

    How to mount your real product on top of the platform layer
    without violating tenant or product isolation.

    [:octicons-arrow-right-24: Integration](INTEGRATION.md)

-   :material-api:{ .lg .middle } **API reference**

    ---

    The full OpenAPI 3.1 schema, served interactively with Swagger UI
    and exportable to Postman, Insomnia, or Bruno.

    [:octicons-arrow-right-24: API reference](api-reference.md)

</div>

!!! tip "Why multi-product?"
    Most teams eventually ship more than one SaaS. The classic mistake
    is to copy-paste the auth, billing, and admin layer into every new
    repo and watch them drift. Plynth hosts many independent products
    on a single deployment — each with its own tenants, users, plans,
    subscriptions, and credits — so the platform layer stays in one
    place, gets fixed once, and every product on top inherits it.
    Cross-product access is explicit, reviewed line by line, and
    enforced by the repository layer.

---

:fontawesome-brands-github: Like what you see?
[**Star Plynth on GitHub**](https://github.com/shubhamkatta/plynth) — it
helps a lot.
