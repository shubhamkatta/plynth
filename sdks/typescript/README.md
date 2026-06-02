# @plynth/sdk

Official TypeScript SDK for the [Plynth](https://github.com/shubhamkatta/plynth) platform.

Zero runtime dependencies. Works in Node 20+, browsers, Cloudflare Workers, and Vercel Edge.

## Install

```bash
npm install @plynth/sdk
```

## Quickstart

```ts
import { PlynthClient, MemoryStore } from "@plynth/sdk";

const client = new PlynthClient({
  baseUrl: "https://api.example.com",
  productSlug: "chatbot",
  tokenStore: new MemoryStore(),
});

await client.auth.login({ email: "you@example.com", password: "..." });
const me = await client.auth.me();
```

## Auth modes

```ts
// 1. User session (the common case)
await client.auth.login({ email, password });
await client.tenants.list();

// 2. Platform admin (your ops backend only — never ship the token to clients)
const admin = new PlynthClient({
  baseUrl: "https://api.example.com",
  adminToken: process.env.PLATFORM_ADMIN_TOKEN,
});
await admin.products.create({ slug: "newapp", name: "New App" });

// 3. Admin god-mode (admin token + default product, no user session)
//    Useful for one-off scripts that want to act as if signed in.
const god = new PlynthClient({
  baseUrl: "https://api.example.com",
  productSlug: "chatbot",
  adminToken: process.env.PLATFORM_ADMIN_TOKEN,
});
await god.tenants.list();
```

## Token storage

| Store              | Where it lives           | Use it for                        |
| ------------------ | ------------------------ | --------------------------------- |
| `MemoryStore`      | In-process (default)     | Servers, short-lived scripts      |
| `LocalStorageStore`| `window.localStorage`    | SPAs (opt-in; XSS exposure)       |
| Custom             | Implement `TokenStore`   | Cookies, IndexedDB, keytar, etc.  |

```ts
class MyKeytarStore implements TokenStore {
  async get() { return JSON.parse(await keytar.getPassword("svc", "tokens") ?? "null"); }
  async set(t) { await keytar.setPassword("svc", "tokens", JSON.stringify(t)); }
  async clear() { await keytar.deletePassword("svc", "tokens"); }
}
```

## Idempotency

Every mutating method on the SDK sends an `Idempotency-Key` automatically. Pass your own when you need to dedupe across retries from a queue:

```ts
const ref = crypto.randomUUID();
await client.credits.consume(
  { feature_key: "credits.ai_completion", amount: "1", reference: ref },
);
```

## Errors

```ts
import { PlynthApiError, PlynthNetworkError } from "@plynth/sdk";

try {
  await client.credits.consume({ feature_key: "x", amount: "1" });
} catch (err) {
  if (err instanceof PlynthApiError) {
    if (err.code === "insufficient_credits") showUpsell();
    else if (err.code === "payment_required") showReactivate();
    else if (err.code === "rate_limited") backoff(err.details);
  } else if (err instanceof PlynthNetworkError) {
    // transport failure; safe to retry
  }
}
```

## Resources

| Namespace              | Maps to              |
| ---------------------- | -------------------- |
| `client.auth`          | `/api/v1/auth/*`     |
| `client.tenants`       | `/api/v1/tenants/*`  |
| `client.users`         | `/api/v1/users/*`    |
| `client.plans`         | `/api/v1/plans`      |
| `client.subscription`  | `/api/v1/subscription/*` |
| `client.credits`       | `/api/v1/credits/*`  |
| `client.roles`         | `/api/v1/roles/*`    |
| `client.products`      | `/api/v1/admin/products/*` (admin-token only) |
| `client.adminEnv`      | `/api/v1/admin/products/{slug}/env/*` (admin-token only) |
| `client.serviceTokens` | `/api/v1/admin/products/{slug}/service-tokens/*` (admin-token only) |
| `client.env`           | `/api/v1/env` (service token only — `X-Service-Token`) |

### Per-product env vars (vault)

Admin: manage values + issue service tokens.

```ts
const admin = new PlynthClient({ baseUrl, adminToken: process.env.PLATFORM_ADMIN_TOKEN });

await admin.adminEnv.set("mayva", "STRIPE_LIVE_KEY", {
  value: "sk_live_xxx",
  is_secret: true,
  description: "Stripe live key",
});

const issued = await admin.serviceTokens.issue("mayva", {
  name: "mayva-prod-backend",
  scopes: ["env:read"],
});
console.log(issued.token);  // "pst_…" — store in your secret manager NOW
```

Product runtime: fetch the vault into `process.env` at boot.

```ts
const runtime = new PlynthClient({
  baseUrl: "https://api.example.com",
  serviceToken: process.env.PLYNTH_SVC_TOKEN!,
});
const env = await runtime.env.fetch();
for (const [k, v] of Object.entries(env)) process.env[k] ??= v;
```

**Never** ship the service token to a browser / mobile / Electron renderer.

## Compatibility

| SDK    | Plynth API |
| ------ | ---------- |
| 0.1.x  | v0.2.x     |

## Links

- Docs: <https://shubhamkatta.github.io/plynth/>
- Integration guide: [`docs/INTEGRATION.md`](https://github.com/shubhamkatta/plynth/blob/main/docs/INTEGRATION.md)
- Changelog: [`CHANGELOG.md`](./CHANGELOG.md)
- Issues: <https://github.com/shubhamkatta/plynth/issues>

## License

MIT — see [`LICENSE`](./LICENSE).
