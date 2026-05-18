---
name: testing
description: Write tests for the platform — unit tests for pure helpers, integration tests for routes + DB. Use whenever the user asks "add a test for X", "write a test that verifies Y", or after introducing a new feature/endpoint. Don't use for production code changes (use `add-feature` / `add-endpoint`).
---

# Testing patterns

## Layout

- `tests/unit/` — pure functions, no DB, no Redis.
- `tests/integration/` — talks to a real Postgres + Redis; uses
  `conftest.py` to spin schema per session.

## Fixtures (conftest)

- `client: AsyncClient` — httpx ASGI transport against the live app.
- A fresh schema is created once per session and dropped at teardown. Tables
  are NOT truncated between tests — write tests that don't depend on row
  count, or add a `_clean_tables` fixture.

## Running

```bash
make test         # all tests
pytest tests/unit -q
pytest -k credits
```

For integration tests, ensure Postgres + Redis are up:
```bash
docker compose up -d db redis
```

## Patterns

### Async HTTP

```python
async def test_login(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/login", json={...})
    assert r.status_code == 200
```

### Tenant isolation

Always write at least one test per resource that:
1. Creates data in tenant A.
2. Logs in as a user in tenant B.
3. Asserts the data is invisible.

### Idempotency

For credit + billing endpoints, run the same call twice with the same
`reference` / `Idempotency-Key` and assert the second is a no-op.

### Provider mocks

`BILLING_PROVIDER=mock` in conftest selects the in-memory provider — no
network calls. To test Stripe-specific paths, use `respx` to intercept HTTPS
calls; never hit Stripe's real API in CI.

## Things to avoid

- Sleeping for time-based logic. Inject a clock instead (refactor the service
  to accept `now` if needed).
- Building chains of fixtures that hide state. Prefer explicit setup in the
  test body for readability.
- Testing private helpers exhaustively. Test through the public surface.
- Mocking the DB. We test against a real Postgres; this scaffold isn't worth
  it without that fidelity.
