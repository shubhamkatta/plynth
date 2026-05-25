# Plynth — Next.js 14 starter

A 5-minute, copy-pasteable Next.js 14 (App Router) starter that
integrates with the Plynth platform. Use it as a reference, or fork it
into your own product.

## What it demonstrates

- **Login** (`POST /api/v1/auth/login`) with the `X-Product-Slug` header.
- **B2C sign-up** (`POST /api/v1/auth/register-individual`).
- **Server-side fetch** of the current user (`GET /api/v1/auth/me`)
  from a server component.
- **HttpOnly cookie** session storage — refresh tokens never touch
  JavaScript.
- **Auto refresh + retry on 401** via `POST /api/v1/auth/refresh`,
  with both tokens rotated.
- **Logout** that revokes the refresh token server-side and clears
  cookies.

## Prerequisites

- A running Plynth API. From the repo root:
  ```bash
  make up        # docker compose up
  make migrate   # apply migrations
  make seed      # default product + plans + admin
  ```
  This seeds a default product slug (typically `demo`) — change
  `NEXT_PUBLIC_PLYNTH_PRODUCT_SLUG` if yours differs.
- **Node 20+** and **npm 10+**.

## Setup

```bash
cd examples/nextjs-starter
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. You will be redirected to `/login`.
Create an account at `/signup`, then return to `/` for the dashboard.

> The agent that scaffolded this starter did NOT run `npm install` —
> the sandbox blocks network installs. You must run it yourself.

## Environment variables

| Var | Purpose |
| --- | --- |
| `PLYNTH_API_URL` | Server-side base URL for the platform (default `http://localhost:8000`). |
| `PLYNTH_PRODUCT_SLUG` | Product slug, server-side. |
| `NEXT_PUBLIC_PLYNTH_PRODUCT_SLUG` | Same slug exposed to the browser (used as a fallback). |

Keep `PLYNTH_PRODUCT_SLUG` and `NEXT_PUBLIC_PLYNTH_PRODUCT_SLUG` in
sync — the slug is not secret.

## Where to look first

1. [`lib/plynth.ts`](./lib/plynth.ts) — the typed API client.
   - Injects `X-Product-Slug` + `Authorization: Bearer …` on every
     request.
   - Refreshes on 401 and retries once.
   - Normalises errors to `PlynthApiError` so you can `switch (err.code)`.
   - Namespaces: `auth.login()`, `auth.me()`, `auth.logout()`,
     `auth.registerIndividual()`, `subscription.get()`. Other catalogue
     endpoints (credits, tenants, users, plans) are left as commented
     placeholders — uncomment when you need them.
2. [`lib/session.ts`](./lib/session.ts) — HttpOnly cookie helpers.
3. [`app/page.tsx`](./app/page.tsx) — the dashboard, a pure server
   component. Demonstrates server-side fetch via the client.
4. [`app/login/actions.ts`](./app/login/actions.ts) — server actions
   for login, register, and sign-out. Branches on `err.code` to surface
   friendly errors.

## File map

```
examples/nextjs-starter/
  app/
    layout.tsx              root layout (Tailwind shell)
    page.tsx                /  — dashboard (server component)
    globals.css             Tailwind directives
    login/
      page.tsx              /login — client form
      actions.ts            server actions: loginAction,
                            registerIndividualAction, signOutAction
    signup/
      page.tsx              /signup — client form (B2C)
  lib/
    plynth.ts               typed API client (auth, subscription, ...)
    session.ts              HttpOnly cookie helpers
  .env.example
  .gitignore
  next.config.mjs
  package.json
  postcss.config.mjs
  tailwind.config.ts
  tsconfig.json
```

## Extending

- **Add a new endpoint** — extend the relevant namespace in
  `lib/plynth.ts`. For example, to add credits, uncomment the
  `credits` block and import it from your component.
- **Add a new page** — create another route under `app/`. Authenticated
  pages should be server components that catch `PlynthApiError` with
  `status === 401` and redirect to `/login` (see `app/page.tsx`).
- **Acting as a child workspace** — pass `actingTenantSlug` to any
  request via the client's `RequestOptions`. The header
  `X-Acting-Tenant-Slug` will be set automatically. List children via
  `GET /api/v1/tenants/children`.

## Production notes

- Cookies set `secure: true` in production. Run the app behind HTTPS.
- The refresh-token cookie has `maxAge` ~29 days; the access-token
  cookie ~1 day. Refresh-on-401 keeps the access token fresh within
  that window.
- The platform admin token is **not** consumed by this starter. Never
  put it in any environment file shipped to the browser. See § 9 of
  `docs/INTEGRATION.md`.

## Further reading

- `docs/INTEGRATION.md` in the repo root — the authoritative
  product-facing API contract (auth flow, headers, error envelope,
  refresh, full endpoint catalogue).
- `docs/ARCHITECTURE.md` — platform-side source of truth.
