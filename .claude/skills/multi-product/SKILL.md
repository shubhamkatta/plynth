---
name: multi-product
description: Enforce product isolation when adding code that touches DB rows owned by a tenant in a product. Use when adding a new model, query, route, webhook, background job, or admin endpoint. Don't use for pure infrastructure changes.
---

# Multi-product rules

The platform hosts many independent SaaS products. Every domain table
carries `product_id NOT NULL` (except `Permission`, the shared catalog).
Every read or write goes through the dual `(product_id, tenant_id)` filter.

## The contract

> Every read or write against a product-scoped table must be filtered by
> both `product_id` and `tenant_id` — **always** — unless explicitly
> bypassed via `bypass_product()` / `bypass_tenant()`.

## Resolution order

| Source                 | Sets                |
| ---------------------- | ------------------- |
| `X-Product-Slug` header| `current_product_id`|
| JWT `pid` claim        | `current_product_id` (and validates header if both present) |
| Webhook subscription lookup | `current_product_id` |
| `with bypass_product():` | disables the filter |

If header and JWT disagree → `403 forbidden`.

## Adding a product-scoped model

```python
class MyModel(
    UUIDPKMixin, TimestampMixin, ProductScopedMixin, TenantScopedMixin, Base
):
    __tablename__ = "my_things"
    # ...
```

`ProductScopedMixin` + `TenantScopedMixin` plug in both `product_id` and
`tenant_id` FKs with cascade deletes. `TenantRepository` then auto-filters
on both.

For a uniqueness constraint that needs to be per-product, scope it:

```python
__table_args__ = (
    UniqueConstraint("product_id", "slug", name="uq_my_things_product_slug"),
)
```

## Adding a route

- **Public route** (login, register, plan listing): depend on `RequireProduct`.
- **Authenticated route**: depend on `CurrentUser` — product context is
  set automatically from the JWT.
- **Webhook**: no header; derive product from the persisted entity the
  event refers to (e.g. `sub.product_id`), then `set_current_product(...)`.
- **Platform-admin route** (sits above products): depend on
  `require_platform_admin`. No product context required.

## Service signatures

Pass `product_id` explicitly:

```python
async def create_tenant(db, *, product_id: UUID, name: str, slug: str, ...): ...
async def list_plans(db, *, product_id: UUID, only_public: bool = True): ...
async def consume(db, *, tenant_id: UUID, product_id: UUID, feature_key, ...): ...
```

Inside the service, scope queries explicitly:

```python
with bypass_product(), bypass_tenant():
    plan = await db.scalar(
        select(Plan).where(Plan.product_id == product_id, Plan.code == code)
    )
```

Or just rely on the repository if you're using `TenantRepository`.

## When you legitimately need to bypass

- **Webhooks** — no header; the event references a known subscription.
- **Platform-admin tools** — `/admin/products` CRUD, cross-product reports.
- **Background sweeps** that iterate every tenant in every product (e.g.
  `suspend_if_grace_expired`).

Wrap in:

```python
with bypass_product(), bypass_tenant():
    ...
```

Bypassed code should be exceptional and reviewed line by line. `grep -rn
bypass_product app/` is the audit trail.

## RBAC + roles per product

System roles (owner/admin/member) are seeded **per product** by
`rbac.ensure_system_roles_for_product(...)` — called automatically on
`POST /admin/products`. Custom tenant-scoped roles are also per-product.

Permissions (the `*:*` catalog) are global — codes are the same across
products. New permission codes go in
`app/services/rbac.SYSTEM_PERMISSIONS`; existing products pick them up
on the next call to `ensure_system_roles_for_product`.

## Adding a new product

```bash
curl -X POST http://localhost:8000/api/v1/admin/products \
  -H "X-Platform-Admin-Token: $PLATFORM_ADMIN_TOKEN" \
  -d '{"name": "ChatBot", "slug": "chatbot"}'
```

This creates the product and seeds its system roles. After that, users
can register inside `chatbot` via `X-Product-Slug: chatbot`.

## Anti-patterns

- Looking up a row by primary key only (`db.get(Model, id)`) on a
  product-scoped table without then checking
  `obj.product_id == current_product_id()`.
- Joining tables from two different products in the same query.
- Caching results across requests without keying on `product_id`.
- Adding a `/admin/...` route that uses tenant JWT auth. Admin auth is
  separate — token-only.
- Forgetting to thread `product_id=` when calling a service from a script
  or background job. The dual-filter will raise rather than silently
  return wrong data, but better to set it upfront.

## Reviewer checklist

- [ ] Every new model is product-scoped (or explicitly documented as global).
- [ ] Service signatures take `product_id` (or derive it from the loaded
      entity).
- [ ] No bare `db.get(Model, id)` on a scoped table without a
      `product_id` follow-up check.
- [ ] Uniqueness constraints include `product_id` when appropriate.
- [ ] Webhook / background paths set the context before doing tenant work.
- [ ] At least one cross-product isolation test added if the surface is
      new.
