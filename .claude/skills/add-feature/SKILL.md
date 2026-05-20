---
name: add-feature
description: Add a new product feature module on top of the platform scaffold. Use whenever the user says "add a feature for X" or "build a new module for Y" — anything that needs models + schemas + service + API routes wired against tenant + RBAC. Skip for one-off endpoints (use `add-endpoint`) or schema-only changes (use `add-migration`).
---

# Adding a new feature module

A *feature* is a vertical slice: model + schemas + service + router, wired
into auth, RBAC, multi-tenancy, and the existing transaction boundary.

**Before you start:** read `docs/ARCHITECTURE.md` — at minimum
§§ 4.1 (module map), 4.2 (schema), 4.3 (scope enforcement), 4.4 (RBAC),
6.1 (existing routes). When you finish, update those same sections
to reflect what you added — per the maintenance contract in `CLAUDE.md`.

## Where to put it

```
app/products/<feature_name>/
  __init__.py
  models.py
  schemas.py
  service.py
  api.py
  permissions.py        # codes added to the RBAC catalog
```

Keep platform-layer code (`app/services/`, `app/api/v1/`) reserved for the
generic concerns. Products live under `app/products/`.

## Steps

1. **Model** — extend `Base` + the appropriate mixins:
   - `UUIDPKMixin`, `TimestampMixin` always.
   - `ProductScopedMixin` + `TenantScopedMixin` for tenant-owned data —
     almost everything. The repository dual-filters on both.
   - `SoftDeleteMixin` if you ever need to undelete.
2. **Schemas** — Pydantic v2 models inheriting `ORMModel` for responses.
3. **Service** — pure async functions taking `AsyncSession` + kwargs. Wrap
   side-effects so a single request = a single transaction. Emit
   `audit.record(...)` for every state change.
4. **API** — small router using `CurrentUser` and
   `Depends(require_permission("feature:action"))`. No business logic here.
5. **Permissions** — add codes to `permissions.py` and register them via
   `rbac.SYSTEM_PERMISSIONS.extend(...)` in your app's startup hook.
6. **Migration** — `make revision m="add <feature>"`, eyeball it, commit.
7. **Wire in** — `app/api/v1/router.py` → include the new router.
8. **Tests** — at least one integration test that exercises the happy path
   through HTTP, asserting tenant isolation.

## Things to avoid

- Reaching into another tenant's data without `bypass_tenant()`, or
  another product's data without `bypass_product()`. See `/multi-product`.
- Putting Pydantic models in `models.py` or SQLAlchemy in `schemas.py`.
- Using sync DB sessions (the entire stack is async).
- Adding routes that don't have a `require_permission` dependency unless they
  are explicitly public (auth endpoints, plan listing).
- Writing business logic in the router. Routers are dumb adapters.
- Catching `Exception` to "make it not crash". See
  `/error-handling-and-audit` for the rules.

## Checklist before opening a PR

- [ ] Models scoped via `ProductScopedMixin` + `TenantScopedMixin` where
      appropriate; uniqueness constraints include `product_id` if codes /
      slugs need to repeat across products.
- [ ] Service emits audit entries (`audit.record` or `audit.audit_action`)
      on every state change. See `/error-handling-and-audit`.
- [ ] Failure paths raise typed `AppError` subclasses, not bare
      `HTTPException`.
- [ ] Routes guarded by `require_permission`.
- [ ] Idempotency-Key honoured if the endpoint mutates billing/credits.
- [ ] At least one integration test for the happy path and one for
      cross-tenant isolation.
- [ ] Migration reviewed and reversible.
- [ ] Docs updated under `docs/` if user-facing concepts change.
