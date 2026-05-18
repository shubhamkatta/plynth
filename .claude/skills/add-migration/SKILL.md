---
name: add-migration
description: Generate, review, and ship a database migration. Use when you've modified an SQLAlchemy model (added a column, table, index, enum value) or when the user explicitly asks for an Alembic migration. Don't use for code-only changes that don't touch the schema.
---

# Adding a migration

## Generate

```bash
make revision m="describe the change in one line"
# or:
docker compose exec api alembic revision --autogenerate -m "..."
```

Autogenerate is a **starting point**, not the final answer. Always open the
generated file and read it before applying.

## Review checklist

- [ ] Constraint and index names match the `NAMING` convention in
      `app/models/base.py` (`ix_…`, `uq_…`, `fk_…`, `pk_…`, `ck_…`).
- [ ] No unexpected drops. If autogenerate wants to drop something you didn't
      remove, your model import probably failed silently — check
      `app/models/__init__.py`.
- [ ] Foreign keys have `ondelete` set (we use `CASCADE` or `SET NULL`).
- [ ] New indexes on hot columns; for production, create them
      `op.create_index(..., postgresql_concurrently=True)` and split out
      `op.execute("COMMIT")` if needed.
- [ ] Enum changes are forward-only: Postgres doesn't allow removing enum
      values. To rename, create new + backfill + drop old in separate releases.
- [ ] Downgrade is implemented — if you genuinely can't reverse, write
      `raise NotImplementedError("forward-only")` and document why.

## Apply

```bash
make migrate
```

## Zero-downtime rule

If the app is live, a single deploy can either change schema OR change code
that reads/writes that schema — not both. The safe sequence:

1. **Deploy 1** — add nullable column / new index.
2. **Deploy 2** — backfill data (one-off script or arq job).
3. **Deploy 3** — switch reads/writes to the new column.
4. **Deploy 4** — drop the old column.

Skip steps only when you're confident there's no in-flight traffic.

## Common pitfalls

- Forgetting to `import` the new model in `app/models/__init__.py` →
  autogenerate misses it.
- Using `sa.Enum` without `create_constraint=False` + explicit `Enum` migration
  helpers — Postgres enums are global types.
- Adding a `NOT NULL` column without `server_default` on a non-empty table —
  the migration will fail. Use nullable + backfill + alter to NOT NULL.
