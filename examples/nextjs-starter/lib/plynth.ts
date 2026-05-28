/**
 * Typed Plynth platform client (server-side) — thin shim over `@plynth/sdk`.
 *
 * Read first: `../README.md`, the upstream `docs/INTEGRATION.md`, and the
 * `@plynth/sdk` README in `sdks/typescript/`.
 *
 * What this file does
 *   - Constructs a per-request `PlynthClient` using a cookie-backed
 *     `TokenStore` that proxies to `lib/session.ts`. Calls from server
 *     components / actions never expose tokens to the browser.
 *   - Re-exports the previous `auth` and `subscription` namespaces so
 *     existing imports (`app/page.tsx`, `app/login/actions.ts`) work
 *     unchanged.
 *   - Adapts the SDK's `MeResponse` / `Subscription` types to the
 *     starter's slightly looser `PlynthUser` / `PlynthSubscription`
 *     shapes so the UI keeps rendering optional slug fields.
 *
 * Where to extend
 *   - For any endpoint not covered by the SDK's resource namespaces,
 *     instantiate a client via `client()` and call the underlying
 *     resource directly (`client().credits.consume({...})`).
 */
import {
  PlynthClient,
  PlynthApiError,
  type MeResponse,
  type Subscription,
  type TokenStore,
  type Tokens,
} from "@plynth/sdk";
import {
  clearSession,
  readSession,
  saveSession,
  type PlynthTokens,
} from "./session";

const BASE_URL = process.env.PLYNTH_API_URL ?? "http://localhost:8000";
const PRODUCT_SLUG =
  process.env.PLYNTH_PRODUCT_SLUG ??
  process.env.NEXT_PUBLIC_PLYNTH_PRODUCT_SLUG ??
  "demo";

class CookieTokenStore implements TokenStore {
  get(): Tokens | null {
    const s = readSession();
    if (!s) return null;
    return {
      access_token: s.access_token,
      refresh_token: s.refresh_token,
      token_type: "bearer",
      expires_at: s.expires_at,
    };
  }

  set(t: Tokens): void {
    saveSession({
      access_token: t.access_token,
      refresh_token: t.refresh_token,
      expires_at: t.expires_at,
    });
  }

  clear(): void {
    clearSession();
  }
}

function client(): PlynthClient {
  return new PlynthClient({
    baseUrl: BASE_URL,
    productSlug: PRODUCT_SLUG,
    tokenStore: new CookieTokenStore(),
  });
}

/* ------------------------------------------------------------------------- */
/* Types (compat with the pre-SDK starter)                                   */
/* ------------------------------------------------------------------------- */

export { PlynthApiError };
export type { PlynthTokens };

export type PlynthUser = MeResponse & {
  product_slug?: string;
  tenant_slug?: string;
};

export type PlynthSubscription = Subscription & {
  plan_code?: string;
};

export interface LoginInput {
  email: string;
  password: string;
  tenant_slug?: string;
}

export interface RegisterIndividualInput {
  email: string;
  password: string;
  full_name?: string;
}

/* ------------------------------------------------------------------------- */
/* Public namespaces                                                         */
/* ------------------------------------------------------------------------- */

export const auth = {
  /** B2C sign-up — creates tenant + owner user + trial sub in one shot. */
  async registerIndividual(input: RegisterIndividualInput): Promise<PlynthTokens> {
    const tokens = await client().auth.registerIndividual(input);
    return {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      expires_at: tokens.expires_at,
    };
  },

  /** Email + password sign-in. */
  async login(input: LoginInput): Promise<PlynthTokens> {
    const tokens = await client().auth.login(input);
    return {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      expires_at: tokens.expires_at,
    };
  },

  /** Current user + permissions. Triggers refresh-once on expired access token. */
  async me(): Promise<PlynthUser> {
    return client().auth.me();
  },

  /** Revoke server-side refresh token + clear cookies (best-effort on network failure). */
  async logout(opts: { allSessions?: boolean } = {}): Promise<void> {
    try {
      await client().auth.logout({ all_sessions: opts.allSessions ?? false });
    } catch {
      // Even if the platform call fails (network, already-revoked), we still
      // want to drop local cookies.
      clearSession();
    }
  },
};

export const subscription = {
  /** Current subscription status; render banners based on `.status`. */
  async get(): Promise<PlynthSubscription> {
    return client().subscription.get();
  },
};

/* ------------------------------------------------------------------------- */
/* Other endpoints                                                            */
/* ------------------------------------------------------------------------- */
//
// Every SDK resource is one `client().<resource>.<method>(…)` away. See
// the @plynth/sdk README for the full surface. Examples:
//
//   await client().credits.consume({ feature_key: "x", amount: "1" });
//   await client().tenants.children();
//   await client().users.list();
//   await client().plans.list();
