# Plynth Admin (Electron)

Cross-platform desktop admin client for the Plynth platform.
Talks to the same REST API documented in
[`docs/INTEGRATION.md`](../../docs/INTEGRATION.md) — no special endpoints,
no privileged backdoor. The desktop wrapper only buys you:

- Tokens in your **OS keychain** (macOS Keychain / Windows Credential
  Manager / libsecret on Linux) via `keytar`, never in browser storage.
- A trusted process for the **platform admin token** — the token never
  touches the renderer; cross-product calls inject the header in the
  main process.
- Auto-refresh of expired access tokens before any call.
- Native menus, single-instance lock, hardened renderer (no nodeIntegration,
  context isolation on, strict CSP, navigation guard).

## What it manages

| Section       | Status        | Endpoints                                                  |
| ------------- | ------------- | ---------------------------------------------------------- |
| Dashboard     | ✅ ready       | `/system/baseUrl`, session                                 |
| Products      | ✅ ready       | `GET/POST /api/v1/admin/products` (platform admin token)   |
| Tenants       | ✅ ready       | `GET/POST /api/v1/tenants` + `:id/{activate,deactivate}`   |
| Users         | ✅ ready       | `GET/POST /api/v1/users` + `:id/{activate,deactivate}`, `DELETE /:id` |
| Roles         | ✅ ready       | `GET/POST /api/v1/roles`, `PATCH /:id`, `POST /assign`, `GET /permissions` |
| Plans         | ✅ ready       | `GET/POST /api/v1/plans`, `PATCH /api/v1/plans/:code`      |
| Subscriptions | ✅ ready       | `GET /api/v1/subscriptions`, `POST /{purchase,change,cancel}` (current tenant) |
| Credits       | ✅ ready       | `GET /api/v1/credits/{wallets,ledger}`, `POST /grant`      |
| Audit         | ✅ ready (temp)| `/api/v1/credits/ledger` as stand-in until `/audit` ships  |
| Settings      | ✅ ready       | per-machine base URL + credential management               |

Every nav item is now wired against the live REST API. The Audit page
will switch from the credits-ledger stand-in to a dedicated `/api/v1/audit`
endpoint once it ships on the platform.

## Run it

```bash
cd apps/admin-electron
npm install
npm run dev
```

The window opens at `http://localhost:5173` (Vite serves the renderer,
Electron loads it). First-launch flow:

1. Click **Platform Admin** on the login screen → paste the token from
   `.env` on the production server (`PLATFORM_ADMIN_TOKEN`). It's stored
   in your keychain and verified by listing products.
2. Pick a **product** in the header dropdown — every tenant-scoped page
   (Tenants, Users, Roles, Plans, Subscriptions, Credits) operates inside
   that product. The admin token gives super-user (`*:*`) access on the
   product's root tenant; switch into a child via `X-Acting-Tenant-Slug`
   (UI for this is on the roadmap).
3. Alternatively, click **User** → sign in as a normal user; `productSlug`
   defaults to `platform`. The user's JWT + RBAC grants apply normally.

Switching API endpoint (e.g. local dev vs production):

- **Settings → API endpoint**, paste `http://localhost:8000` (or your
  Fly / DO URL), Save. All subsequent requests use it.

## Architecture (1-page)

```
src/
  shared/                 types + IPC channel constants (no Node imports)
  main/                   privileged process
    index.ts              window, CSP, perms, single-instance, menus
    config.ts             on-disk config (userData/config.json)
    api/
      client.ts           HTTP client + 401 refresh-once
      errors.ts           normalize anything → ApiError; run() wraps to Result<T>
      secrets.ts          keytar service "dev.plynth.admin"
    ipc/{auth,products,audit,system}.ts   ipcMain.handle() per channel
  preload/index.ts        contextBridge.exposeInMainWorld("api", api)
  renderer/               sandboxed React UI
    main.tsx              MantineProvider + Notifications + Modals + Query + HashRouter
    App.tsx               auth gate + route table
    lib/api.ts            unwraps Result<T> → throws ApiError on failure
    lib/notify.ts         Mantine notifications wrapper (success/info/warn/error)
    components/           AppShell, PageHeader, ErrorBoundary, StubPage
    features/             one folder per nav item (auth, products, audit, …)
```

### Security defaults

All `BrowserWindow` instances use:

- `contextIsolation: true`
- `nodeIntegration: false`
- `sandbox: true`
- `webSecurity: true`
- Strict Content-Security-Policy installed via
  `session.webRequest.onHeadersReceived`
- `setPermissionRequestHandler` denies everything by default
- `will-navigate` blocks navigation away from the bundle
- `setWindowOpenHandler` routes externals through `shell.openExternal`

The preload is the only bridge. Every IPC channel is enumerated in
`src/shared/ipc-channels.ts` — anything not in that list is unreachable
from the renderer, by design.

### Error envelope

Every IPC handler runs through `run<T>()` which returns
`Result<T> = { ok: true, data: T } | { ok: false, error: ApiError }`.
The renderer's `lib/api.ts` unwraps it so React code just sees promises;
`isApiError(e)` and `describeError(e)` produce friendly toasts via
`notify.error(title, e)`.

HTTP errors from the platform pass through unchanged — same `code`,
`message`, `details` you'd see hitting the API directly. Validation
errors are flattened into a single readable string.

### Auth flows

- **User session**: `POST /auth/login` (with `X-Product-Slug`); access +
  refresh tokens persisted in keychain; expired access tokens are
  refreshed transparently inside `call<T>()` once per request before
  re-throwing 401.
- **Platform admin token**: stored as a separate keychain entry; calls
  marked `asPlatformAdmin: true` inject `X-Platform-Admin-Token` and
  skip the user `Authorization` header.

## Build distributables

```bash
npm run dist:mac     # .dmg (arm64 + x64)
npm run dist:win     # NSIS installer
npm run dist:linux   # AppImage + .deb
```

Code-signing is **stubbed** in `electron-builder.yml` — drop in your
Apple Developer ID / Windows EV cert before shipping public releases.
Until then, builds are unsigned and Gatekeeper / SmartScreen will warn.

## Adding a new section

Per the **doc-as-source-of-truth** rule in
[`../../CLAUDE.md`](../../CLAUDE.md), when you wire a new section:

1. Add the route in `App.tsx`, nav item in `components/AppShell.tsx`.
2. Add IPC channels in `shared/ipc-channels.ts` + handler in
   `main/ipc/<section>.ts`.
3. Add the namespace to `BridgeApi` in `shared/types.ts` and surface it
   in `preload/index.ts`.
4. Build the feature folder under `renderer/features/<section>/`.
5. Update [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) §
   "Electron admin client" with the new endpoints consumed.

## Known gaps

- `/api/v1/audit` doesn't exist on the platform yet — the Audit page
  reads `/api/v1/credits/ledger` as a stand-in. Swap the path in
  `main/ipc/audit.ts` once the real endpoint ships.
- Role assignment (binding a user to a role with optional child-tenant
  scope) is exposed via `api.roles.assign()` but not yet surfaced in the
  Roles UI. Add a "Bind user" action there next.
- Subscriptions view assumes the platform supports one subscription per
  tenant (single-record `GET /api/v1/subscriptions`). Multi-sub flows
  will need a list view.
- Auto-update server not configured; `electron-updater` is included but
  needs a feed URL (S3 / generic / GitHub releases).
