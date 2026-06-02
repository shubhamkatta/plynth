# Changelog

All notable changes to `@plynth/sdk` will be documented here. Versions
follow [Semantic Versioning](https://semver.org/). The compatibility
contract with the Plynth API is documented in the README.

## [Unreleased]

### Added
- `client.adminEnv` — CRUD for the per-product env-vars vault
  (`set`, `patch`, `list`, `reveal`, `delete`). Uses the platform
  admin token.
- `client.serviceTokens` — issue / list / revoke per-product service
  tokens (`pst_…`, returned ONCE on `issue`).
- `client.env.fetch()` — product-runtime fetch via the new
  `serviceToken` constructor option. Sends `X-Service-Token` and
  skips Bearer / admin headers.
- New types: `EnvVarSetRequest`, `EnvVarPatchRequest`,
  `EnvVarListItem`, `EnvVarDetail`, `ServiceTokenCreateRequest`,
  `ServiceTokenResponse`, `ServiceTokenIssued`.
- Test coverage for the new resources (12 → 17 cases).

## [0.1.0] — 2026-05-28

Initial alpha release.

### Added
- `PlynthClient` — isomorphic client using native `fetch` (Node 20+,
  browsers, Cloudflare Workers, Vercel Edge). Zero runtime dependencies.
- Auth resolution order: per-call override → user JWT → platform-admin
  god-mode. Admin paths auto-route through `X-Platform-Admin-Token`.
- Pluggable token storage via `TokenStore` interface. Ships
  `MemoryStore` (default) and `LocalStorageStore` (browser, opt-in).
- `Idempotency-Key` auto-generated on mutating resource methods.
- Refresh-once-on-401 with token-pair rotation persisted to the store.
- Typed error envelope: `PlynthApiError` (`.status`, `.code`, `.message`,
  `.details`) and `PlynthNetworkError`.
- Resource namespaces: `auth`, `tenants`, `users`, `plans`,
  `subscription`, `credits`, `roles`, `products` (admin-only).
- Targets Plynth API **v0.2.x**.

[Unreleased]: https://github.com/shubhamkatta/plynth/compare/sdks/typescript-v0.1.0...HEAD
[0.1.0]: https://github.com/shubhamkatta/plynth/releases/tag/sdks/typescript-v0.1.0
