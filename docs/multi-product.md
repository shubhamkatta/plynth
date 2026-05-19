# Multi-product

This platform layer hosts **multiple SaaS products** on a single deployment.
Each product is fully isolated — its own tenants, users, plans, subscriptions,
credits, audit log. The same email or company can register in two different
products without conflict; nothing crosses between them.

## Entity tree

```
Product
├── Plan (per product)
│   └── PlanFeature
├── Tenant (per product)
│   ├── User
│   ├── Subscription
│   ├── Invoice
│   ├── CreditWallet / CreditLedger
│   ├── AuditLog
│   ├── IdempotencyKey
│   └── UserRole
├── Role (per product — system + custom)
│   └── RolePermission → Permission (GLOBAL catalog, shared across products)
```

**Every domain table carries `product_id NOT NULL`** (except `Permission`,
the shared catalog of permission codes). Repository filters apply
`product_id = :pid AND tenant_id = :tid` to every read.

## Uniqueness

| Table   | Constraint                          |
| ------- | ----------------------------------- |
| products| `(slug)` unique                     |
| tenants | `(product_id, slug)` unique         |
| plans   | `(product_id, code)` unique         |
| users   | `(tenant_id, email)` unique         |
| roles   | `(product_id, tenant_id, name)` unique |

Same tenant slug or plan code can live in `producta` and `productb` simultaneously.

## How a request resolves a product

1. Client sends `X-Product-Slug: producta` header.
2. Middleware-level dependency (`resolve_product`) looks the slug up
   (Redis cached, 5 min TTL) and sets `current_product_id()`.
3. If the route also requires auth, `get_current_user` reads the JWT's `pid`
   claim and verifies it matches the header (if both are present).
4. Repositories pick up both context vars and filter.

| Endpoint class           | Provides product context via      |
| ------------------------ | --------------------------------- |
| `POST /auth/register`    | `X-Product-Slug` header           |
| `POST /auth/login`       | `X-Product-Slug` header           |
| `GET  /plans`            | `X-Product-Slug` header           |
| Any authenticated route  | JWT `pid` claim                   |
| `POST /webhooks/billing` | derived from subscription lookup  |
| `/admin/products`        | none — sits above products        |

If a client sends both the header and a JWT, the values must match — else
the request is rejected `403 forbidden` ("product header does not match token").

## JWT shape

Access + refresh tokens carry:

```
{
  "sub": "<user_uuid>",
  "tid": "<tenant_uuid>",
  "pid": "<product_uuid>",
  "typ": "access" | "refresh",
  "iat": ..., "exp": ..., "jti": "..."
}
```

`pid` is required for any authenticated request to succeed.

## Bootstrapping a new product

Two paths:

1. **Seed script** — edit `scripts/seed.py` and add a `Product` row.
   `make seed` is idempotent.
2. **Platform-admin endpoint** — `POST /api/v1/admin/products` with
   `X-Platform-Admin-Token: <env PLATFORM_ADMIN_TOKEN>`:

   ```bash
   curl -X POST http://localhost:8000/api/v1/admin/products \
     -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name": "ChatBot", "slug": "chatbot"}'
   ```

   The endpoint also seeds the per-product system roles (owner / admin / member)
   so that registration immediately works inside the new product.

The platform-admin token is set via `PLATFORM_ADMIN_TOKEN` env var. Unset →
admin endpoints return 403 ("platform admin is not configured").

## Per-product plans

Plans are scoped to a product. Create plans for a new product after creating
the product:

```bash
# In Product chatbot, with an admin user's JWT
curl -X POST http://localhost:8000/api/v1/plans \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Product-Slug: chatbot" \
  -H "Content-Type: application/json" \
  -d '{"code": "pro", "name": "Pro", "price_cents": 2900, "currency": "USD",
       "interval": "month", "trial_days": 14,
       "features": [{"feature_key": "seats", "limit_value": "25"}]}'
```

## Bypassing the product filter

Mirror the tenant bypass:

```python
from app.core.tenant import bypass_product

with bypass_product():
    # cross-product query — admin tooling, sweep jobs, webhook lookup
    rows = await db.scalars(select(Model))
```

Grep audit: `grep -rn bypass_product app/`. Should be a small known set
(webhook handler, admin router, sweep jobs).

## Webhook product resolution

Billing webhooks don't carry the product header. The handler:
1. Parses + verifies the signature.
2. Looks up the Subscription by `provider_subscription_id`.
3. Reads `sub.product_id` and sets the context for downstream calls.

If the subscription is unknown (older deletion, foreign event) it logs a
warning and returns 200 — never raises into the provider's retry loop.

## Migration from a single-product deployment

Out of scope for this scaffold — there's no production data to migrate. If
you fork an older single-product version:

1. Create a single Product row with the desired slug.
2. Backfill `product_id` on every existing tenant / plan / etc.
3. Add the `NOT NULL` constraint after the backfill.

Do this in three deploys (additive nullable → backfill → enforce NOT NULL),
per the zero-downtime rule in `docs/deployment.md`.
