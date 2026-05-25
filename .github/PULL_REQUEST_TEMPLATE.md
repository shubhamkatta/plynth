<!--
Thanks for contributing to Plynth! Please fill in every section.
Keep the PR focused: one logical change per PR makes review easier.
-->

## Summary

<!-- 1-3 sentences on the *why*. What problem does this PR solve? -->

## Changes

<!-- Bullet list of what's touched: routes, services, models, migrations,
     Electron screens, docs, infra, etc. -->

-
-
-

## Doc-as-source-of-truth contract

`docs/ARCHITECTURE.md` is the source of truth for this codebase. Any
change to a contract (new route, new column, new permission code, new
config key, new job type, new storage collection, new flow step) MUST
update the doc in the same PR.

- [ ] `docs/ARCHITECTURE.md` updated if any contract changed — OR this PR
      touches no contracts.
- [ ] Focused doc named in the `ARCHITECTURE.md` § 8 touchpoint table also
      updated where applicable.

## Test plan

<!-- What did you run locally? What should the reviewer verify?
     Include exact commands and expected output where it helps. -->

-
-

## Checklist

- [ ] `make lint && make typecheck && make test` all pass locally.
- [ ] New product/tenant-scoped queries go through `TenantRepository` and
      don't bypass the repository.
- [ ] Audit log entry (`audit.record(...)` / `audit.audit_action(...)`)
      emitted for every state change.
- [ ] Cross-product / cross-tenant isolation test added if this introduces
      a new surface.
- [ ] Migration is idempotent + reversible (or marked forward-only with a
      written reason).
- [ ] No bare `except Exception`; no secrets leaked into logs or audit
      `diff`.

## Related issues

<!-- Use `Closes #N` so GitHub auto-links and auto-closes on merge. -->

Closes #
