# plynth-sdk

Official Python SDK for the [Plynth](https://github.com/shubhamkatta/plynth) platform. Sync + async; one runtime dep (`httpx`).

## Install

```bash
pip install plynth-sdk
```

## Quickstart — sync

```python
from plynth_sdk import PlynthClient, MemoryStore

with PlynthClient(
    base_url="https://api.example.com",
    product_slug="chatbot",
    token_store=MemoryStore(),
) as client:
    client.auth.login({"email": "you@example.com", "password": "..."})
    me = client.auth.me()
```

## Quickstart — async

```python
from plynth_sdk import AsyncPlynthClient, MemoryStore

async with AsyncPlynthClient(
    base_url="https://api.example.com",
    product_slug="chatbot",
    token_store=MemoryStore(),
) as client:
    await client.auth.login({"email": "you@example.com", "password": "..."})
    me = await client.auth.me()
```

## Auth modes

```python
# 1. User session
client.auth.login({"email": email, "password": password})
client.tenants.list()

# 2. Platform admin (ops backend only — never ship the token to clients)
with PlynthClient(
    base_url="https://api.example.com",
    admin_token=os.environ["PLATFORM_ADMIN_TOKEN"],
) as admin:
    admin.products.create({"slug": "newapp", "name": "New App"})

# 3. Admin god-mode (admin token + default product, no user session)
with PlynthClient(
    base_url="https://api.example.com",
    product_slug="chatbot",
    admin_token=os.environ["PLATFORM_ADMIN_TOKEN"],
) as god:
    god.tenants.list()
```

## Token storage

| Store         | Where it lives              | Use it for                       |
| ------------- | --------------------------- | -------------------------------- |
| `MemoryStore` | In-process (default)        | Servers, short-lived scripts     |
| `FileStore`   | JSON file at mode `0600`    | CLIs, single-process daemons     |
| Custom        | Implement `TokenStore`      | Keyring, Vault, Secrets Manager  |

```python
from plynth_sdk import FileStore

store = FileStore("~/.config/plynth/tokens.json")
```

## Idempotency

Every mutating method on the SDK sends an `Idempotency-Key` automatically. Pass a `reference` in the body when you need application-level dedupe across retries:

```python
import uuid

ref = str(uuid.uuid4())
client.credits.consume({
    "feature_key": "credits.ai_completion",
    "amount": "1",
    "reference": ref,
})
```

## Errors

```python
from plynth_sdk import PlynthApiError, PlynthNetworkError

try:
    client.credits.consume({"feature_key": "x", "amount": "1"})
except PlynthApiError as exc:
    if exc.code == "insufficient_credits":
        show_upsell()
    elif exc.code == "payment_required":
        show_reactivate()
    elif exc.code == "rate_limited":
        backoff(exc.details)
except PlynthNetworkError:
    pass  # transport failure; safe to retry
```

## Resources

| Namespace             | Maps to                              |
| --------------------- | ------------------------------------ |
| `client.auth`         | `/api/v1/auth/*`                     |
| `client.tenants`      | `/api/v1/tenants/*`                  |
| `client.users`        | `/api/v1/users/*`                    |
| `client.plans`        | `/api/v1/plans`                      |
| `client.subscription` | `/api/v1/subscription/*`             |
| `client.credits`      | `/api/v1/credits/*`                  |
| `client.roles`        | `/api/v1/roles/*`                    |
| `client.products`     | `/api/v1/admin/products/*` (admin)   |
| `client.admin_env`    | `/api/v1/admin/products/{slug}/env/*` (admin) |
| `client.service_tokens` | `/api/v1/admin/products/{slug}/service-tokens/*` (admin) |
| `client.env`          | `/api/v1/env` (service token — `X-Service-Token`) |

### Per-product env vars (vault)

Admin — manage values + issue service tokens:

```python
with PlynthClient(base_url=BASE, admin_token=os.environ["PLATFORM_ADMIN_TOKEN"]) as admin:
    admin.admin_env.set("mayva", "STRIPE_LIVE_KEY",
                       {"value": "sk_live_xxx", "is_secret": True,
                        "description": "Stripe live key"})
    issued = admin.service_tokens.issue("mayva",
                                        {"name": "mayva-prod-backend",
                                         "scopes": ["env:read"]})
    print(issued["token"])   # pst_…  — store in your secret manager NOW
```

Product runtime — fetch the vault into `os.environ` at boot:

```python
with PlynthClient(base_url=BASE, service_token=os.environ["PLYNTH_SVC_TOKEN"]) as c:
    env = c.env.fetch()
for k, v in env.items():
    os.environ.setdefault(k, v)
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
