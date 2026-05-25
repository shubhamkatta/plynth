# Integration Guide — for products consuming this platform

> **Share this document with the team / Claude Code session integrating
> a product against the platform.** It's self-contained: an LLM reading
> only this file can build a correct client. If anything here drifts
> from the implementation, the **`docs/ARCHITECTURE.md` source-of-truth
> contract** governs — see § 13 "If you find a discrepancy".

Audience: a developer (or AI assistant) building a **product** — web,
Electron, mobile, CLI, or that product's backend — that talks to this
platform over HTTPS. You do **not** need read access to the platform
codebase to integrate.

Related: `docs/ARCHITECTURE.md` (full HLD/LLD, platform-owner-facing) ·
`docs/postman_collection.json` (runnable requests).

---

## 0. What you need from the platform owner

Ask once, store as configuration in your product:

| Item | Example | Notes |
| --- | --- | --- |
| **Platform base URL** | `https://api.example.com` | All endpoints under `/api/v1/...` |
| **Your product slug** | `chatbot` | Identifies which product this client is for. Not secret — frontends include it. |
| **CORS allow-listed origin** *(web only)* | `https://chatbot.example.com` | Platform owner adds your origin to `CORS_ORIGINS`. Not needed for Electron / mobile / server. |
| **Plan codes** for upsell UI | `free`, `pro`, `team` | List via `GET /api/v1/plans`. |
| **Credit feature keys** *(if metered)* | `credits.ai_completion` | List via `GET /api/v1/credits/wallets` once a tenant exists. |
| **Platform admin token** *(only if you'll create products yourself)* | 64-hex | **Secret.** Never put in client code. Only your backend / ops should hold it. |

---

## 1. What the platform handles (don't reimplement)

- **Identity** — sign-up, sign-in, password hashing (Argon2id), JWT issue/refresh, server-side refresh-token revocation, password change.
- **Tenancy** — every account lives in a `Tenant` (B2B "company" or B2C "individual"). Parent → child tenants with role-gated context switching.
- **RBAC + IAM** — `resource:action` permissions, system roles (owner/admin/member) per product, custom roles with optional per-child scope.
- **Plans & subscriptions** — catalog, trial → active → past-due → grace → suspended → cancelled, upgrade/downgrade with proration.
- **Billing** — Stripe (or other) under a provider abstraction. Webhooks land on the platform; your client just reads status.
- **Credits / metered usage** — append-only ledger, atomic consume with optimistic dedupe, plan-driven monthly grants.
- **Audit** — every state change persisted with actor + scope.
- **Lifecycle ops** — invite, activate / deactivate, soft-delete, log out everywhere.

## 2. What is NOT the platform's job (your job)

- Your product's domain logic (the actual app).
- Your own UI / UX.
- Email delivery (your platform owner plugs SES/Postmark; you display flows).
- Object storage (S3 etc.).
- Cross-product SSO (each product is independent).
- Anything not in the endpoint catalogue § 6.

---

## 3. Authentication flow

### 3.1 Sign-up

Two flavours; pick based on your product shape.

**B2B (company / team account):**
```http
POST /api/v1/auth/register
X-Product-Slug: <yourProductSlug>
Content-Type: application/json

{
  "tenant_name": "Acme Inc",
  "tenant_slug": "acme",                   // user-chosen org slug, lowercase, [a-z0-9-]
  "email":       "owner@acme.example.com",
  "password":    "S3cretPassword!",        // ≥ 12 chars
  "full_name":   "Alice Owner"
}
→ 201 { "access_token", "refresh_token", "token_type":"bearer", "expires_at" }
```

**B2C (individual user, tenant of 1):**
```http
POST /api/v1/auth/register-individual
X-Product-Slug: <yourProductSlug>
Content-Type: application/json

{
  "email":     "alice@gmail.example.com",
  "password":  "S3cretPassword!",
  "full_name": "Alice Rivers"               // optional
}
→ 201 { access_token, refresh_token, expires_at }
```

The platform creates the tenant, owner user, and a trial subscription
on the cheapest public plan in one shot. The same email is allowed to
sign up in *different* products independently.

### 3.2 Sign-in

```http
POST /api/v1/auth/login
X-Product-Slug: <yourProductSlug>
Content-Type: application/json

{
  "email":       "owner@acme.example.com",
  "password":    "S3cretPassword!",
  "tenant_slug": "acme"                    // optional; needed only if same
                                           // email is in multiple tenants of
                                           // the same product
}
→ 200 { access_token, refresh_token, expires_at }
```

### 3.3 Token storage

Platform issues two tokens:
- `access_token` — JWT, 15 min lifetime. Send on every authed request as `Authorization: Bearer ...`.
- `refresh_token` — JWT, 30 day lifetime. Only used to mint a new access token. **Store securely; never log; never expose to renderer/JS.**

| Client | Recommended storage |
| --- | --- |
| Web (SPA hitting platform directly) | `accessToken` in memory; `refreshToken` in `HttpOnly` cookie set by your own backend if you have one, else `localStorage` (accept XSS risk) |
| Web (with own backend) | Refresh handled server-side; browser holds neither token directly |
| Electron | `keytar` (Keychain / Credential Manager / libsecret). Store + refresh in the **main process**; IPC results to the renderer. Renderer never sees tokens. |
| iOS | Keychain |
| Android | EncryptedSharedPreferences / Keystore-backed |
| CLI / server | OS secret manager (Vault, AWS Secrets Manager, `pass`, etc.) |

### 3.4 Refresh on 401

The platform returns `401 { code: "unauthorized" }` when the access token
is expired or invalid. The flow:

```
1. request → 401
2. call POST /api/v1/auth/refresh { refresh_token }
3. if 200 → store new pair; retry original request once
4. if 401 → refresh token is dead; redirect to login
```

Each refresh **rotates** both tokens — the old `refresh_token` is
revoked. Always replace both.

### 3.5 Logout

```http
POST /api/v1/auth/logout
Authorization: Bearer <access>
X-Product-Slug:  <yourProductSlug>

{ "refresh_token": "...", "all_sessions": false }
```

Set `all_sessions: true` to revoke every refresh token for the user
(use this on password change, account compromise, "log out everywhere").

---

## 4. Required headers on every request

| Header | When | Value |
| --- | --- | --- |
| `Authorization: Bearer <accessToken>` | Every authenticated request | from login/refresh |
| `X-Product-Slug: <yourProductSlug>` | Every request (recommended on authed too — defence-in-depth) | constant for your product |
| `X-Acting-Tenant-Slug: <child-slug>` | Optional, when a parent-tenant admin acts as a child workspace | from `GET /tenants/children` |
| `Idempotency-Key: <uuid>` | Every mutating call (POST/PATCH/DELETE), especially in offline-retry contexts | client-generated uuid, store with the request |
| `Content-Type: application/json` | Bodies | always JSON |

If both `X-Product-Slug` and the JWT's `pid` claim are present and
disagree, the platform returns `403 { code: "forbidden" }`. They must
match — which they always will if you hard-code the slug in your client.

---

## 5. Error envelope + status codes

Every error response is a uniform JSON envelope:

```json
{
  "code":    "machine_readable_code",
  "message": "Human-friendly explanation",
  "details": { "...": "context-specific" }
}
```

| Status | `code` examples | What it means |
| --- | --- | --- |
| 400 | `invalid_signature` | Bad request shape |
| 401 | `unauthorized` | Missing / expired / invalid token |
| 402 | `insufficient_credits`, `payment_required` | Wallet too low, or subscription suspended |
| 403 | `forbidden` | Authenticated but lacking permission |
| 404 | `not_found` | Resource doesn't exist *in your current scope* |
| 409 | `conflict` | Unique constraint, state conflict, idempotency replay with different body |
| 422 | `validation_failed` | Pydantic rejected the body; `details.errors` lists per-field issues |
| 429 | `rate_limited` | Slow down; see `Retry-After` header |
| 503 | `service_unavailable` | Platform datastore unreachable; safe to retry with backoff |

Always branch on `code`, not `message`. Messages may be re-worded;
codes are stable.

---

## 6. Endpoint catalogue (for product clients)

Anchored to UI actions, not REST verbs. Full request bodies in
`docs/postman_collection.json`.

### 6.1 Auth & identity

| UI action | Endpoint |
| --- | --- |
| Sign up (company) | `POST /api/v1/auth/register` |
| Sign up (individual) | `POST /api/v1/auth/register-individual` |
| Sign in | `POST /api/v1/auth/login` |
| Refresh tokens | `POST /api/v1/auth/refresh` |
| Sign out current session | `POST /api/v1/auth/logout` |
| Sign out everywhere | `POST /api/v1/auth/logout` `{all_sessions: true}` |
| Change password | `POST /api/v1/auth/password` |
| Forgot password | `POST /api/v1/auth/password/forgot` `{email}` — always returns 200 (no enumeration). Non-prod responses include the raw `reset_token` for testing. Prod returns just `{ok: true}` — the platform's notification provider stub is what you'll wire to email a link `<your-app>/reset?token=…`. |
| Configure refresh-token TTL (admin) | `PATCH /api/v1/admin/products/{slug}` `{settings: {auth: {refresh_ttl_days: <1..365>}}}` — overrides the platform default for this product only. Honored by /login, /refresh, /register, /auth/google. Out-of-range values fall back to platform default. |
| Reset password (consume token) | `POST /api/v1/auth/password/reset` `{token, new_password}` — single-use, expires in 1 hour. Revokes every existing refresh token. |
| Sign in with Google (OAuth2) | `POST /api/v1/auth/google` `{code, redirect_uri}` — you run the redirect dance on your side, then forward the `code` here. Returns `TokenPair`. New users are rejected unless the product opts in to `settings.features.google_auto_provision = true` (then a B2C-style tenant is created on first login). Platform-wide config: `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` env vars; unset → 401 "not configured". |
| Read current user + permissions | `GET /api/v1/auth/me` |

### 6.2 Subscriptions & plans

| UI action | Endpoint |
| --- | --- |
| Show plan catalogue (pricing page) | `GET /api/v1/plans` *(public; needs only `X-Product-Slug`)* |
| Show current sub status / banner | `GET /api/v1/subscription` |
| Purchase / start a paid plan | `POST /api/v1/subscription/purchase` |
| Upgrade / downgrade | `POST /api/v1/subscription/change` |
| Cancel (at period end or immediate) | `POST /api/v1/subscription/cancel` |

Display rules:
- `subscription.status ∈ {trial, active}` → full app access.
- `past_due` → soft banner ("payment failed, retrying").
- `grace` → harder banner ("update payment by <grace_ends_at>").
- `suspended` / `cancelled` / `expired` → block app, show pay/reactivate CTA.

### 6.3 Credits (metered usage)

| UI action | Endpoint |
| --- | --- |
| Read all credit balances | `GET /api/v1/credits/wallets` |
| Read ledger history | `GET /api/v1/credits/ledger?limit=100` |
| Consume credits for a user action | `POST /api/v1/credits/consume` |
| Grant credits *(admin only)* | `POST /api/v1/credits/grant` |

Pattern for any client action that costs credits:
```
client generates ref = uuid()
POST /credits/consume
  { feature_key, amount, reason, reference: ref }
if 200 → proceed
if 402 (insufficient_credits) → show upsell
on network failure → retry with the SAME ref (no double-charge)
```

### 6.4 Team / users (B2B or family B2C)

| UI action | Endpoint |
| --- | --- |
| List teammates | `GET /api/v1/users` |
| Invite teammate | `POST /api/v1/users` `{email, role_codes}` |
| Update teammate profile | `PATCH /api/v1/users/{user_id}` |
| Activate / deactivate teammate | `POST /api/v1/users/{user_id}/(de)activate` |
| Soft-delete teammate | `DELETE /api/v1/users/{user_id}` |
| List role catalog | `GET /api/v1/roles` |
| List permission catalog | `GET /api/v1/roles/permissions` |

Inviting auto-generates a random password (the platform does not yet
send invite emails — the platform owner will wire that). If you need
to onboard the invitee, call `POST /api/v1/auth/password` flow with
them or implement a password-reset email yourself when available.

### 6.5 Workspaces / child tenants & act-as

| UI action | Endpoint |
| --- | --- |
| List my workspaces I can switch into | `GET /api/v1/tenants/children` |
| Create a child workspace | `POST /api/v1/tenants` `{name, slug}` |
| Act inside a child workspace | any route + `X-Acting-Tenant-Slug: <child-slug>` |
| Rename / update workspace | `PATCH /api/v1/tenants/{id}` |
| Deactivate / activate workspace | `POST /api/v1/tenants/{id}/(de)activate` |

`GET /tenants/children` returns `{slug, name, can_act_as, reason}` —
render a picker; grey out entries where `can_act_as=false` and show
`reason` on hover.

---

## 7. Idempotency

Always include `Idempotency-Key: <uuid>` on mutating calls
(`POST` / `PATCH` / `DELETE`). It must be unique **per logical
operation**, not per HTTP attempt. On retry, send the same key —
the platform returns the original response.

**Two layers of dedupe**:
- `Idempotency-Key` header → general HTTP retry safety.
- `reference` body field (on `/credits/consume`, future `/jobs`) →
  application-level dedupe. Use this for offline queues where many
  user actions may collapse to one server call.

For an offline-capable client (Electron typically):
1. Generate uuid when the user clicks → store on disk with the pending request.
2. Try POST; if network fails, queue.
3. On reconnect, retry with same key + reference. Platform replays the first response.

---

## 8. Webhooks (only if your product runs its own backend)

The platform itself **does not push events back to your product yet**
(outbound webhooks are designed in `docs/ARCHITECTURE.md` § 6.2.6 for
the Jobs API but not generally implemented for billing events).

Today's options if you need to react to billing events:
- **Poll** `GET /api/v1/subscription` and `GET /api/v1/credits/wallets`
  on a schedule (e.g. every 5 min from your backend, or on app focus
  from the client).
- Ask the platform owner to add outbound webhooks (small extension).

---

## 9. Minimal client implementation

### 9.1 TypeScript (Electron main process)

```typescript
import { randomUUID } from "node:crypto";
import keytar from "keytar";

const BASE_URL     = "https://api.example.com";
const PRODUCT_SLUG = "chatbot";
const KEYTAR_SVC   = "com.your.product";

type Tokens = { access_token: string; refresh_token: string; expires_at: string };

async function loadTokens(): Promise<Tokens | null> {
  const json = await keytar.getPassword(KEYTAR_SVC, "tokens");
  return json ? JSON.parse(json) : null;
}
async function saveTokens(t: Tokens) {
  await keytar.setPassword(KEYTAR_SVC, "tokens", JSON.stringify(t));
}
async function clearTokens() {
  await keytar.deletePassword(KEYTAR_SVC, "tokens");
}

interface ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
}

async function refreshTokens(): Promise<Tokens> {
  const cur = await loadTokens();
  if (!cur) throw Object.assign(new Error("no refresh token"), { status: 401, code: "unauthorized" });
  const r = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ refresh_token: cur.refresh_token }),
  });
  if (!r.ok) { await clearTokens(); throw await asApiError(r); }
  const next = await r.json();
  await saveTokens(next);
  return next;
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit & {
    actingTenantSlug?: string;
    idempotencyKey?:   string;
    skipAuth?:         boolean;
  } = {},
): Promise<T> {
  const { actingTenantSlug, idempotencyKey, skipAuth, ...rest } = init;

  const send = async (tokens: Tokens | null) => {
    const headers: Record<string, string> = {
      "X-Product-Slug": PRODUCT_SLUG,
      ...(rest.body  ? { "Content-Type": "application/json" } : {}),
      ...(tokens     ? { Authorization: `Bearer ${tokens.access_token}` } : {}),
      ...(actingTenantSlug ? { "X-Acting-Tenant-Slug": actingTenantSlug } : {}),
      ...(idempotencyKey   ? { "Idempotency-Key":      idempotencyKey   } : {}),
      ...(rest.headers as Record<string, string> ?? {}),
    };
    return fetch(`${BASE_URL}${path}`, { ...rest, headers });
  };

  let tokens = skipAuth ? null : await loadTokens();
  let res = await send(tokens);

  // One-shot refresh on 401.
  if (res.status === 401 && !skipAuth && tokens) {
    try { tokens = await refreshTokens(); }
    catch { throw await asApiError(res); }
    res = await send(tokens);
  }

  if (!res.ok) throw await asApiError(res);
  return res.status === 204 ? (undefined as T) : await res.json();
}

async function asApiError(r: Response): Promise<ApiError> {
  const body = await r.json().catch(() => ({}));
  return Object.assign(new Error(body.message ?? r.statusText), {
    status:  r.status,
    code:    body.code   ?? "http_error",
    details: body.details ?? {},
  });
}

// --- usage ----------------------------------------------------------------

export async function signUp(email: string, password: string, fullName?: string) {
  const tokens = await api<Tokens>("/api/v1/auth/register-individual", {
    method:   "POST",
    body:     JSON.stringify({ email, password, full_name: fullName }),
    skipAuth: true,
  });
  await saveTokens(tokens);
}

export async function consumeCredits(featureKey: string, amount: string) {
  return api("/api/v1/credits/consume", {
    method:         "POST",
    idempotencyKey: randomUUID(),
    body: JSON.stringify({
      feature_key: featureKey,
      amount,
      reference:   randomUUID(),
    }),
  });
}
```

### 9.2 Python (CLI / server-side product backend)

```python
import json, uuid, httpx, keyring

BASE = "https://api.example.com"
PRODUCT = "chatbot"
SVC = "com.your.product"

class ApiError(Exception):
    def __init__(self, status, code, message, details):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.details = status, code, details

def load_tokens(): raw = keyring.get_password(SVC, "tokens"); return json.loads(raw) if raw else None
def save_tokens(t): keyring.set_password(SVC, "tokens", json.dumps(t))
def clear_tokens():   keyring.delete_password(SVC, "tokens")

class Platform:
    def __init__(self, base=BASE, slug=PRODUCT):
        self._base = base
        self._slug = slug
        self._client = httpx.Client(base_url=base, timeout=30.0)

    def _headers(self, *, auth=True, acting=None, idem=None):
        h = {"X-Product-Slug": self._slug}
        if auth:
            t = load_tokens()
            if t: h["Authorization"] = f"Bearer {t['access_token']}"
        if acting: h["X-Acting-Tenant-Slug"] = acting
        if idem:   h["Idempotency-Key"]      = idem
        return h

    def _refresh(self):
        t = load_tokens()
        if not t: raise ApiError(401, "unauthorized", "no refresh token", {})
        r = self._client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
        if r.status_code != 200: clear_tokens(); raise self._error(r)
        save_tokens(r.json())

    def call(self, method, path, *, json_body=None, auth=True, acting=None, idem=None):
        r = self._client.request(method, path, json=json_body,
                                 headers=self._headers(auth=auth, acting=acting, idem=idem))
        if r.status_code == 401 and auth:
            self._refresh()
            r = self._client.request(method, path, json=json_body,
                                     headers=self._headers(auth=auth, acting=acting, idem=idem))
        if r.status_code >= 400: raise self._error(r)
        return None if r.status_code == 204 else r.json()

    @staticmethod
    def _error(r):
        try: body = r.json()
        except Exception: body = {}
        return ApiError(r.status_code, body.get("code","http_error"),
                        body.get("message", r.text), body.get("details", {}))

# Usage
p = Platform()
p.call("POST", "/api/v1/auth/login", auth=False,
       json_body={"email": "...", "password": "..."})
p.call("POST", "/api/v1/credits/consume",
       idem=str(uuid.uuid4()),
       json_body={"feature_key":"credits.ai_completion","amount":"1","reference":str(uuid.uuid4())})
```

---

## 10. Common mistakes to avoid

- **Don't reimplement auth.** No `bcrypt`, no `jwt.encode` on the client side. The platform mints tokens; you store + present them.
- **Don't store the platform admin token in client code.** It's for the platform owner's ops only.
- **Don't log tokens, passwords, or `Idempotency-Key` values.** Treat them like secrets.
- **Don't use the access token as if it's long-lived.** It expires in ~15 min. Wire refresh up before you ship.
- **Don't ignore `code` in error responses.** Branch on it (especially `insufficient_credits` → upsell, `payment_required` → reactivate flow, `rate_limited` → backoff).
- **Don't use HTTP retries without `Idempotency-Key`.** You'll double-charge / double-create. Pick a key once per logical operation.
- **Don't bypass `X-Product-Slug` even on authed calls.** It's defence-in-depth — set it once in your HTTP client.
- **Don't poll for everything.** For credit balance / subscription status, refresh on app focus, after known mutations, and every 5+ min — not every second.
- **Don't put `*` in CORS.** If you have a web frontend, hand specific origins to the platform owner.
- **Don't share refresh tokens between devices.** Each install / browser has its own. Rotation tracks per-jti server-side.

---

## 11. Future capabilities (designed, not yet implemented)

When you see these in the platform changelog, the contracts are
already specified in `docs/ARCHITECTURE.md`:

- **Jobs API** (`POST /api/v1/jobs`, polling + SSE stream, type-registered
  handlers, optional outbound webhooks on completion) — spec in § 6.2.
  Use for: transcription, export, ML inference, bulk import, project sync.
- **Storage API** (`PUT/GET /api/v1/storage/{collection}/{key}`,
  optimistic concurrency, presigned blob uploads, delta sync) — spec
  in § 6.3. Use for: documents, preferences, recent files, cross-device
  state.

Build your client with these in mind — leave the namespaces `/jobs` and
`/storage` clear, and design your local data layer so it can later
treat the platform as canonical.

---

## 12. Snippet to paste into your project's `CLAUDE.md`

Copy this block verbatim into your product's `CLAUDE.md` so its Claude
Code session understands how to talk to the platform.

```markdown
## Platform integration (do not reimplement these capabilities)

This product consumes a shared platform layer for **identity, tenancy,
RBAC, plans, subscriptions, credits, and audit**. Authoritative
reference: `docs/INTEGRATION.md` (copied from the platform repo) and
the platform's OpenAPI at `<BASE_URL>/docs`.

**Hard rules:**

1. **Never roll our own** auth, password hashing, JWT issuance,
   subscription state, credit ledger, RBAC, or audit. Call the platform.
2. Every HTTP call to the platform must include:
   - `Authorization: Bearer <accessToken>`  (except `/auth/register*`,
     `/auth/login`, `/auth/refresh`, `/plans`)
   - `X-Product-Slug: <PRODUCT_SLUG>`        (always — defence in depth)
   - `Idempotency-Key: <uuid>`               (on every POST/PATCH/DELETE)
   - `X-Acting-Tenant-Slug: <child-slug>`    (only when the user is
     working inside a child workspace)
3. Store tokens in the OS secure store (`keytar` for Electron;
   Keychain/Keystore for mobile; HttpOnly cookie via own backend for web).
   **Never** put them in `localStorage` in production code or log them.
4. On `401`, call `POST /auth/refresh` once with the stored refresh
   token, replace BOTH stored tokens with the response, and retry the
   original request. On a second `401`, redirect to login.
5. Branch on the error `code` (not `message`):
   `insufficient_credits` → show upsell · `payment_required` → reactivate
   flow · `forbidden` → permission missing · `rate_limited` → backoff with
   `Retry-After` · `validation_failed` → highlight `details.errors`.
6. For any user action that costs credits: generate a uuid, pass it as
   `reference` to `POST /credits/consume`, and use the same uuid in any
   retry. The platform dedupes.
7. Display subscription banners by `subscription.status`:
   - `trial` / `active` → no banner · `past_due` → soft · `grace` → hard
     with countdown to `grace_ends_at` · `suspended` / `cancelled` /
     `expired` → block the app, surface reactivate CTA.
8. The product slug + base URL come from environment / build config —
   never hard-code in committed source.
9. The platform admin token (`PLATFORM_ADMIN_TOKEN`) lives only in the
   platform owner's ops environment. Never ship it. Never request it
   from end-users.

**When asked to implement a feature** that overlaps with the
platform's responsibilities, **stop** and check `docs/INTEGRATION.md`
§ 6 first. If the platform already covers it (auth, tenancy, billing,
credits, audit, RBAC), call the platform endpoint instead of building
locally. If you genuinely need something not in the catalogue, file a
request with the platform owner — don't shim it in the client.

**Storing user data**: if it's per-user product data (documents,
preferences, project state), the platform's **Storage API** (designed
but not yet implemented; see § 6.3 of the platform's
`docs/ARCHITECTURE.md`) will own it. Build local persistence behind an
interface so we can swap to the platform Storage API when it ships.

**Long-running work** (transcription, export, ML, bulk import, sync):
the platform's **Jobs API** (designed; § 6.2) will own it. Don't put
multi-second compute in the request path of our backend; if we must do
it now, queue it locally behind a `JobLike` interface so the swap is
mechanical when Jobs ships.
```

---

## 13. If you find a discrepancy

If the behaviour you observe differs from this document, the
implementation might have moved without the doc keeping up. Report
back to the platform owner with: the request (headers + body),
response (status + body), and which section of this doc it disagrees
with. The platform's `docs/ARCHITECTURE.md` § 8 forces both code and
docs to ship in the same PR — discrepancies are bugs.

The platform OpenAPI at `<BASE_URL>/docs` is generated from code and
is always current — use it as a tiebreaker.

---

## 14. Changelog references

- `2026-05-19` — multi-product platform live (`X-Product-Slug` header introduced).
- `2026-05-18` — parent → child act-as via `X-Acting-Tenant-Slug` shipped.
- `2026-05-19` — B2C `/auth/register-individual` shipped (`Tenant.type=individual`).
- (future) Jobs API — to be linked here when shipped.
- (future) Storage API — to be linked here when shipped.
