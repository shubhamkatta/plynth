---
name: add-endpoint
description: Add a single HTTP endpoint to an existing router. Use for small additions like "expose a new GET /things/{id}/stats" or "add a POST /users/me/avatar". Don't use this for a brand-new module (use `add-feature` instead) or for DB-shape changes only (use `add-migration`).
---

# Adding an endpoint

Use this when the model + service already exist and you only need to expose a
new HTTP shape.

**Before you start:** scan `docs/ARCHITECTURE.md` § 6.1 to confirm the
endpoint isn't already documented (or designed-but-not-implemented in
§ 6.2 / 6.3). When you finish, **add a row to § 6.1** (the Electron
endpoint catalogue) AND **add the request to `docs/postman_collection.json`** —
both are part of the doc-as-source-of-truth contract in `CLAUDE.md`.

## Pattern

```python
@router.get(
    "/{thing_id}/stats",
    response_model=ThingStatsResponse,
    dependencies=[Depends(require_permission("things:read"))],
)
async def thing_stats(
    thing_id: UUID,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ThingStatsResponse:
    return await thing_svc.stats(db, thing_id=thing_id)
```

## Checklist

- [ ] Router lives under `app/api/v1/` (or `app/products/<x>/api.py`).
- [ ] Product context:
   - Authenticated routes: depend on `CurrentUser` (product set from JWT).
   - Unauthenticated public routes: depend on `RequireProduct`.
   - Platform-admin routes: depend on `require_platform_admin`.
   See `/multi-product`.
- [ ] Pydantic request/response models in `app/schemas/` (or product schemas).
- [ ] Auth: `user: CurrentUser` for any non-public route.
- [ ] Permission: `Depends(require_permission("..."))`.
- [ ] Tenant isolation comes for free via `TenantRepository`; don't reach
      across tenants without `bypass_tenant()`.
- [ ] Errors raised as `AppError` subclasses, not bare `HTTPException` (the
      global handler converts them to JSON).
- [ ] If the endpoint mutates billing/credits, accept `Idempotency-Key` via
      `Depends(get_idempotency_key)` and pass through to the service.

## Anti-patterns

- Business logic inside the route function (move to a service).
- `try / except Exception` swallowing — let `AppError`s bubble. See
  `/error-handling-and-audit` for which exception type to raise.
- Embedding SQL in the route (push to the repository/service).
- Forgetting `response_model` — without it, you may leak fields.
- Mutating state without an audit entry. Wrap the service call in
  `audit.audit_action(...)` or call `audit.record(...)` explicitly.
