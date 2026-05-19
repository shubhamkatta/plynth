---
name: multi-tenant
description: Enforce tenant isolation when adding code that touches DB rows owned by a tenant. Use when the user adds a new model, a new query, a new admin endpoint, a webhook handler, or a background job — anything that could leak across tenants. Don't use for pure infrastructure changes.
---

> Tenancy is *one half* of the scoping story. Every tenant-scoped table
> also carries `product_id`, and `TenantRepository` applies a dual
> `(product_id, tenant_id)` filter. See `/multi-product` for product
> rules; the rest of this skill covers tenant-specific patterns.

# Multi-tenant rules

## The contract

> Every read or write against a tenant-owned table must be filtered by the
> currently authenticated tenant — **always** — unless explicitly bypassed.

## Mechanism

1. Tenant-owned models include `TenantScopedMixin` (adds `tenant_id` FK +
   index).
2. The auth dependency `get_current_user` sets a `ContextVar`:
   `set_current_tenant(user.tenant_id)`.
3. `TenantRepository` reads that var and injects
   `WHERE tenant_id = :current` on every query.
4. Inserts auto-populate `tenant_id` from the context if you don't set it.

## When you legitimately need to bypass

- **Login** — you don't know the tenant until you've found the user.
- **Webhooks** — no authenticated user.
- **Platform-admin tools** — cross-tenant reporting / migrations.
- **Background jobs that iterate every tenant** — e.g. nightly billing sweep.

Always wrap those in:

```python
with bypass_tenant():
    ...
```

Bypassed code should be exceptional and reviewed line by line. `grep -rn
bypass_tenant app/` is the audit trail.

When you bypass the filter inside admin tooling, write an audit entry
naming the actor + the cross-tenant action. See
`/error-handling-and-audit`.

## Adding a new tenant-scoped model

```python
class MyModel(UUIDPKMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "my_things"
    # ...
```

That's all — repository + tenancy enforcement come for free.

## Adding a child-tenant feature

Child tenants share the parent's subscription + billing. Don't issue a second
subscription for them. Use `Tenant.parent_id` to walk up if a feature should
inherit from the parent.

## Parent → child access (act-as)

Parent-tenant users can scope a single request to a child via
`X-Acting-Tenant-Slug: <child-slug>`. The auth dependency validates
hierarchy + product config + parent-tenant config + RBAC and, if all
green, sets `current_tenant_id()` to the child for the lifetime of
that request.

When you add a new route that reads or writes tenant data:

- Filter queries by `current_tenant_id() or user.tenant_id`, **not**
  `user.tenant_id` alone. The first form picks up the child when
  acting-as; the fallback is just defensive.
- When passing `tenant_id=` into a service, use the same pattern.
- Audit rows automatically gain `acting_from_tenant_id` (the home
  tenant) — no manual plumbing needed. `audit.record(...)` reads the
  acting-from context var.

Config gates you should respect when adding a new "switch-like" feature:

- `Product.settings.features.allow_parent_child_access` (default true)
- `Tenant.settings.allow_child_access` (default true)

Both must be true. Either can disable the feature without touching
the other.

`UserRole.scope_tenant_id` semantics:
- `NULL` → applies in every tenant the user can act in.
- `= X`  → applies only when the current scope is tenant X.

`user_has_permission(..., tenant_id=...)` accepts an explicit scope —
use it when you need to evaluate a permission against the home tenant
specifically (e.g. before allowing the switch itself).

See `docs/multi-tenancy.md` for the full design.

## Cross-tenant data exposure heuristics

When reviewing a PR, ask:
- Does this query touch a tenant-scoped table without going through a
  `TenantRepository`?
- Does this admin endpoint return data joined from multiple tenants? If yes,
  is the request-time permission a platform-admin role (not a tenant role)?
- Does the response leak any `tenant_id` or related foreign keys that would
  let a curious client iterate UUIDs?

## Things to avoid

- Pulling rows by primary key directly (`db.get(Model, id)`) on a
  tenant-scoped model without then checking `obj.tenant_id == current_tenant`
  — `get()` bypasses the filter.
- Adding a "platform admin" view by re-using a tenant route with a flag.
  Create a separate `/admin/...` mount with its own permission.
- Caching results across requests without keying on `tenant_id`.
