# RBAC

## Model

- `Permission` — `code = resource:action`, e.g. `users:create`,
  `subscriptions:cancel`.
- `Role` — named bundle of permissions. `tenant_id IS NULL` ⇒ system role.
- `RolePermission` — many-to-many.
- `UserRole` — binds a user to a role, optionally scoped to a child tenant.

## Wildcards

Permission strings support two-segment wildcards:
- `users:*` — every action on `users`.
- `*:*` — super-admin.

Matching happens at check time in `services/rbac._matches`. Avoid evaluating
wildcards in DB queries — keep it in Python.

## System roles (seeded)

| Role   | Permissions                                                                                                  |
| ------ | ------------------------------------------------------------------------------------------------------------ |
| owner  | `*:*`                                                                                                        |
| admin  | tenant, user, role mgmt; subscription read/purchase/change/cancel; credit read/grant; audit read; `staff:manage` |
| member | tenant/user/subscription read; credit read + consume                                                          |

### Acme (`acme-practice`) roles

Extra per-product roles in `PRODUCT_SYSTEM_ROLES["acme-practice"]`: `practitioner`,
`assistant`, `patient`. Acme's backend gates on 28 permission codes; **every one
must exist in the global catalog** (a test enforces this), otherwise non-owner
users get 403s. Newer codes: `dashboard:read`, `analytics:read`, `alert:read`,
`message:read`, `staff:manage`.

| Role | Notable grants |
| ---- | -------------- |
| `owner` | `*:*` (includes `settings:manage`, `staff:manage`) |
| `admin` | `staff:manage` (plus the tenant/user/billing set above) |
| `practitioner` | clinical set, `inbox:read/send`, `dashboard:read`, `analytics:read`, `alert:read`, `message:read`, `subscriptions:read` — **not** `staff:manage`, `settings:manage` or `subscriptions:change` |
| `clinic_admin` | office manager: `settings:manage`, `staff:manage`, `subscriptions:read/change`, `payment:read/manage`, `availability:read/manage`, `client:read/create/update`, `dashboard:read`, `analytics:read`, `digest:read`, `alert:read`. **Excludes** `note:*`, `message:read`, `inbox:*`, `approval:decide`, `gdpr:*` (special-category data / clinical judgement) |
| `assistant` | `client:read`, booking, `inbox:read` |
| `patient` | `portal:read`, `booking:create` only |

Role grants are **additive on re-seed** (`ensure_system_roles_for_product`): new
codes reach existing roles when `scripts.seed_acme` runs; nothing is revoked.

### How a product selects its template

The roles above are the `acme-practice` entry in
`rbac.PRODUCT_SYSTEM_ROLES` — a template for a multi-practitioner professional
practice. A product chooses one with

```
products.settings.rbac.system_roles_template = "acme-practice"
```

falling back to the product's own **slug** when that key is absent, so products
created before the key keep their roles with no migration.

Two reasons the indirection exists rather than keying on the slug alone: a slug
is a public identifier chosen for URLs while a template is a shape several
products may share, and a product could not be renamed without silently losing
its staff roles. ⚠️ `ensure_system_roles_for_product` runs on **every
registration**, so a template that stops resolving does not fail loudly — new
users simply arrive with only `owner` / `admin` / `member`. Pointing an existing
product at a template it did not have before will likewise create those roles
in it on the next registration.

Custom tenant-scoped roles can be created via `POST /roles` with any subset of
existing permissions.

## Adding a permission

1. Append the code to `SYSTEM_PERMISSIONS` in `services/rbac.py`.
2. (Optional) Add it to the appropriate system role in `SYSTEM_ROLES`.
3. Re-run `make seed` (idempotent).
4. Protect the route with `Depends(require_permission("your:perm"))`.

For per-product permissions, create
`app/products/<x>/permissions.py` and merge into the catalog at startup.

## Scope

`UserRole.scope_tenant_id` lets the same user hold different roles in parent
vs. child tenants. Permissions are evaluated **in the current request's
tenant scope** (which is the user's home tenant by default, or the child
tenant when they're acting-as via `X-Acting-Tenant-Slug`).

- `scope_tenant_id IS NULL` → binding applies in every tenant scope.
  Standard owner / admin / member bindings created on registration are NULL.
- `scope_tenant_id == X` → binding applies **only** when the request is
  scoped to tenant X. Useful for delegating "admin of child east" without
  giving the user parent-level powers.

`user_has_permission(db, user, code)` reads `current_tenant_id()` and
includes both NULL-scope bindings and bindings matching the current scope.
You can pass an explicit `tenant_id=` to evaluate against a specific
scope (used by the act-as dependency to check the permission in the
*home* tenant before allowing the switch).

See `docs/multi-tenancy.md` ("Parent → child access") for the full rules.
