# Multi-tenancy

## Model

**Shared database, shared schema with `tenant_id` discriminator.**
Selected for operational simplicity at moderate scale (<10k tenants). Trade-off
matrix:

| Approach            | Isolation | Ops cost | Per-tenant cost | When                |
| ------------------- | --------- | -------- | --------------- | ------------------- |
| Shared schema (this)| Logical   | Low      | Low             | SaaS, default       |
| Schema-per-tenant   | Strong    | Medium   | Medium          | Compliance pressure |
| DB-per-tenant       | Strongest | High     | High            | Enterprise on-prem  |

Migrating up the ladder (shared → schema-per-tenant) is straightforward if you
keep the tenant filter centralised — which this scaffold does.

## Hierarchy

```
Tenant (is_root=True)
└── Tenant (parent_id, is_root=False)        # workspace / department / subsidiary
    └── Tenant ...                            # NOT allowed by default — see service
```

Only a single level of child tenants is allowed. Edit
`app/services/tenant.create_tenant` to relax this.

## B2B vs B2C — `Tenant.type`

`Tenant.type` is `company` (default) or `individual`. Behaviour is identical
under the hood — the tenant is still the billing / audit / RBAC boundary —
but the marker lets product UIs render team-aware vs single-user flows
and lets analytics segment without joining `users`.

| Endpoint | Tenant created | `type` |
| --- | --- | --- |
| `POST /api/v1/auth/register` | caller supplies `tenant_name` + `tenant_slug` | `company` (default) |
| `POST /api/v1/auth/register-individual` | platform derives slug (`usr-<8hex>`) + name from `full_name` or email local-part | `individual` |
| `POST /api/v1/tenants` (admin creating child) | caller supplies `name` + `slug` | inherits caller's default — `company` |

An "individual" tenant is just a tenant of 1. The owner can still invite
teammates later via `POST /api/v1/users` — the marker doesn't cap headcount,
it's just a hint to the product UI. Same plans, same credits, same audit
trail.

## Parent → child access (act-as)

A user in a parent tenant can act inside one of its direct children, with
their request automatically scoped to the child. Activation: send
`X-Acting-Tenant-Slug: <child-slug>` on any authenticated request.

**Three gates must all approve:**

1. **Hierarchy** — target's `parent_id` must equal the user's home `tenant_id`.
2. **Configuration** — both flags default true; either can disable:
   - `Product.settings.features.allow_parent_child_access` (per-product kill switch)
   - `Tenant.settings.allow_child_access` (per-parent-tenant kill switch)
3. **RBAC** — user must have **either**:
   - `tenants:act_as_child` permission evaluated in their home tenant
     (i.e. their org-wide bindings grant it — owner via `*:*`, admin
     explicitly), **or**
   - any `UserRole` binding with `scope_tenant_id == target.id` (an
     explicit delegated role inside that child).

When a switch happens:
- `current_tenant_id()` returns the child id (used by every repository
  and route to scope queries).
- `acting_from_tenant_id()` returns the user's home tenant id, which
  `audit.record(...)` automatically writes to `audit_log.acting_from_tenant_id`.
  So every audit row reconstructs "who in the parent did this in the child".
- The JWT is unchanged — `pid` and `tid` still describe the user's
  identity, not the current request scope.

### Permission scoping

`UserRole.scope_tenant_id` semantics, finally honored:

- `NULL` → role applies in every tenant the user can act in
  (owner / admin / member bindings created on registration are NULL).
- `= X`  → role applies **only** when the request is scoped to tenant X.

So an `admin` binding with `scope_tenant_id = child-east` lets the user
act as east *and* makes them admin once they're inside east — but
gives them nothing in the parent.

### Discovery

`GET /api/v1/tenants/children` returns every direct child of the user's
home tenant with a `can_act_as` flag and a `reason` when the answer is
false. Drop it into a "switch tenant" picker.


## Enforcement

- Every tenant-owned model mixes in `TenantScopedMixin` (`tenant_id` column +
  index).
- Every read/write goes through `TenantRepository` which injects
  `WHERE tenant_id = :current` automatically.
- The active tenant lives in a `ContextVar` set by `get_current_user`.
- The **only** way to bypass is `with bypass_tenant():` — grep for it during
  reviews. It's required for:
  - Login (before we know the tenant).
  - Webhook handlers (no authenticated user).
  - Platform-admin tooling (cross-tenant reporting).

## Defence in depth (optional)

For regulated workloads, enable Postgres Row Level Security:

```sql
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON users
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

Then in `get_db`, set the GUC after opening the connection. The repository
filter then acts as a redundancy layer; even a forgotten filter cannot leak.

## Cross-tenant features

When you need cross-tenant data (e.g. an admin dashboard), do:

```python
with bypass_tenant():
    rows = await db.scalars(select(Model).where(...))
```

Audit access — every bypassed read in admin code paths should emit an audit
log entry.
