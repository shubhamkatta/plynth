# Changelog

All notable changes to `plynth-sdk` will be documented here. Versions
follow [Semantic Versioning](https://semver.org/). The compatibility
contract with the Plynth API is documented in the README.

## [Unreleased]

### Added
- `client.admin_env` (sync + async) — CRUD for the per-product
  env-vars vault (`set`, `patch`, `list`, `reveal`, `delete`).
- `client.service_tokens` — issue / list / revoke per-product
  service tokens (`pst_…`, returned ONCE on `issue`).
- `client.env.fetch()` — product-runtime fetch via the new
  `service_token=` constructor argument. Sends `X-Service-Token`
  and skips Authorization / admin headers.
- New TypedDicts: `EnvVarSetRequest`, `EnvVarPatchRequest`,
  `EnvVarListItem`, `EnvVarDetail`, `ServiceTokenCreateRequest`,
  `ServiceTokenResponse`, `ServiceTokenIssued`.
- 6 new pytest cases covering admin CRUD, reveal, token issuance,
  and the service-token auth path (sync + async).

## [0.1.0] — 2026-05-28

Initial alpha release.

### Added
- `PlynthClient` (sync) and `AsyncPlynthClient` (async) sharing one
  HTTP layer. Single runtime dep: `httpx`.
- Auth resolution order: per-call override → user JWT → platform-admin
  god-mode. Admin paths auto-route through `X-Platform-Admin-Token`.
- Pluggable token storage via `TokenStore` Protocol. Ships
  `MemoryStore` (default) and `FileStore` (JSON file at mode 0600).
- `Idempotency-Key` auto-generated on mutating resource methods.
- Refresh-once-on-401 with token-pair rotation persisted to the store.
- Typed error hierarchy: `PlynthError` → `PlynthApiError`
  (`.status`, `.code`, `.message`, `.details`) and `PlynthNetworkError`.
- Resource namespaces: `auth`, `tenants`, `users`, `plans`,
  `subscription`, `credits`, `roles`, `products` (admin-only).
- Context-manager support: `with PlynthClient(...) as c` and
  `async with AsyncPlynthClient(...) as c` manage the HTTP pool.
- `mypy --strict` clean on the public surface.
- Targets Plynth API **v0.2.x**.

[Unreleased]: https://github.com/shubhamkatta/plynth/compare/sdks/python-v0.1.0...HEAD
[0.1.0]: https://github.com/shubhamkatta/plynth/releases/tag/sdks/python-v0.1.0
