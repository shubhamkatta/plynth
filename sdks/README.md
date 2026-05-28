# Plynth SDKs

Official client libraries for the [Plynth](https://github.com/shubhamkatta/plynth) platform.

| SDK             | Path                                             | Package name                                            | Status |
| --------------- | ------------------------------------------------ | ------------------------------------------------------- | ------ |
| TypeScript / JS | [`typescript/`](./typescript/)                   | [`@plynth/sdk`](https://www.npmjs.com/package/@plynth/sdk) (not yet published) | alpha  |
| Python          | [`python/`](./python/)                           | [`plynth-sdk`](https://pypi.org/project/plynth-sdk/) (not yet published)       | alpha  |

Both SDKs:
- Mirror the same auth resolution rules (user JWT > platform admin > admin god-mode)
- Auto-send `X-Product-Slug`, `X-Acting-Tenant-Slug`, and `Idempotency-Key` on mutating calls
- Refresh access tokens once on `401`, then retry the original request
- Parse the platform's `{code, message, details}` error envelope into typed exceptions
- Expose pluggable token storage (memory by default; opt-in file / browser stores; bring your own)

Coverage: all 38 endpoints documented in [`docs/INTEGRATION.md`](../docs/INTEGRATION.md) § 6. The designed-but-not-yet-implemented Jobs and Storage APIs (`docs/ARCHITECTURE.md` § 6.2 / § 6.3) will land in 0.2.x once the server-side ships.

## Compatibility

| SDK    | Plynth API |
| ------ | ---------- |
| 0.1.x  | v0.2.x     |

## Contributing

Both SDKs share the same contract — `docs/INTEGRATION.md` is the source of truth. When you add a new resource or change auth semantics, update **both** SDKs in the same PR and add tests in both.

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) at the repo root.
