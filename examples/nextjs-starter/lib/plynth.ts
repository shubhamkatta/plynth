/**
 * Typed Plynth platform client (server-side).
 *
 * Read first: `../README.md` and the upstream `docs/INTEGRATION.md`.
 *
 * What it does
 *   - Injects `X-Product-Slug` on every request.
 *   - Injects `Authorization: Bearer <access>` from the HttpOnly cookie.
 *   - On 401, calls `/api/v1/auth/refresh` once, replaces both tokens,
 *     and retries the original request.
 *   - Normalises errors to a `PlynthApiError` carrying `status` + `code`
 *     so callers can branch on `code` (per platform contract).
 *
 * Where to extend
 *   - Add a typed wrapper under the relevant namespace (auth, subscription,
 *     credits, users, tenants, ...). Don't sprinkle raw `request()` calls
 *     through your app code.
 */
import { randomUUID } from "node:crypto";
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

/* ------------------------------------------------------------------------- */
/* Types                                                                     */
/* ------------------------------------------------------------------------- */

export interface PlynthUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  product_id: string;
  product_slug?: string;
  tenant_id: string;
  tenant_slug?: string;
  permissions: string[];
}

export interface PlynthSubscription {
  id: string;
  status:
    | "trial"
    | "active"
    | "past_due"
    | "grace"
    | "suspended"
    | "cancelled"
    | "expired";
  plan_code: string;
  current_period_end: string | null;
  trial_ends_at: string | null;
  grace_ends_at: string | null;
}

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

export class PlynthApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "PlynthApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/* ------------------------------------------------------------------------- */
/* Internal HTTP                                                             */
/* ------------------------------------------------------------------------- */

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Skip auth header + refresh dance (for /auth/login, /auth/register*, /auth/refresh). */
  skipAuth?: boolean;
  /** When set, sent as X-Acting-Tenant-Slug to scope into a child workspace. */
  actingTenantSlug?: string;
  /** Optional idempotency key; auto-generated for mutating calls if absent. */
  idempotencyKey?: string;
}

function buildHeaders(
  tokens: PlynthTokens | null,
  opts: RequestOptions,
): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Product-Slug": PRODUCT_SLUG,
    Accept: "application/json",
  };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (tokens && !opts.skipAuth) {
    headers.Authorization = `Bearer ${tokens.access_token}`;
  }
  if (opts.actingTenantSlug) {
    headers["X-Acting-Tenant-Slug"] = opts.actingTenantSlug;
  }
  const method = opts.method ?? "GET";
  if (method !== "GET") {
    headers["Idempotency-Key"] = opts.idempotencyKey ?? randomUUID();
  }
  return headers;
}

async function parseError(res: Response): Promise<PlynthApiError> {
  let body: { code?: string; message?: string; details?: Record<string, unknown> } = {};
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  return new PlynthApiError(
    res.status,
    body.code ?? "http_error",
    body.message ?? res.statusText,
    body.details ?? {},
  );
}

async function refreshTokens(current: PlynthTokens): Promise<PlynthTokens> {
  const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Product-Slug": PRODUCT_SLUG,
    },
    body: JSON.stringify({ refresh_token: current.refresh_token }),
    cache: "no-store",
  });
  if (!res.ok) {
    clearSession();
    throw await parseError(res);
  }
  const next = (await res.json()) as PlynthTokens;
  saveSession(next);
  return next;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";

  const send = async (tokens: PlynthTokens | null): Promise<Response> =>
    fetch(`${BASE_URL}${path}`, {
      method,
      headers: buildHeaders(tokens, opts),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });

  let tokens = opts.skipAuth ? null : readSession();
  let res = await send(tokens);

  // One-shot refresh + retry on 401.
  if (res.status === 401 && !opts.skipAuth && tokens) {
    try {
      tokens = await refreshTokens(tokens);
    } catch {
      throw await parseError(res);
    }
    res = await send(tokens);
  }

  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* ------------------------------------------------------------------------- */
/* Public namespaces                                                         */
/* ------------------------------------------------------------------------- */

export const auth = {
  /** B2C sign-up — creates tenant + owner user + trial sub in one shot. */
  async registerIndividual(
    input: RegisterIndividualInput,
  ): Promise<PlynthTokens> {
    const tokens = await request<PlynthTokens>(
      "/api/v1/auth/register-individual",
      { method: "POST", body: input, skipAuth: true },
    );
    saveSession(tokens);
    return tokens;
  },

  /** Email + password sign-in. */
  async login(input: LoginInput): Promise<PlynthTokens> {
    const tokens = await request<PlynthTokens>("/api/v1/auth/login", {
      method: "POST",
      body: input,
      skipAuth: true,
    });
    saveSession(tokens);
    return tokens;
  },

  /** Current user + permissions. Triggers refresh on expired access token. */
  async me(): Promise<PlynthUser> {
    return request<PlynthUser>("/api/v1/auth/me");
  },

  /** Revoke server-side refresh token + clear cookies. */
  async logout(opts: { allSessions?: boolean } = {}): Promise<void> {
    const tokens = readSession();
    if (tokens) {
      try {
        await request<void>("/api/v1/auth/logout", {
          method: "POST",
          body: {
            refresh_token: tokens.refresh_token,
            all_sessions: opts.allSessions ?? false,
          },
        });
      } catch {
        // Best-effort. Even if the platform call fails (network, already-revoked),
        // we still want to drop local cookies below.
      }
    }
    clearSession();
  },
};

export const subscription = {
  /** Current subscription status; render banners based on `.status`. */
  async get(): Promise<PlynthSubscription> {
    return request<PlynthSubscription>("/api/v1/subscription");
  },

  // Placeholders — uncomment + type when you wire pricing / billing flows.
  // async purchase(input: { plan_code: string }): Promise<PlynthSubscription> {
  //   return request("/api/v1/subscription/purchase", { method: "POST", body: input });
  // },
  // async change(input: { plan_code: string }): Promise<PlynthSubscription> {
  //   return request("/api/v1/subscription/change", { method: "POST", body: input });
  // },
  // async cancel(input: { at_period_end?: boolean } = {}): Promise<PlynthSubscription> {
  //   return request("/api/v1/subscription/cancel", { method: "POST", body: input });
  // },
};

/* ------------------------------------------------------------------------- */
/* Other endpoints — leave commented until you actually need them.            */
/* See docs/INTEGRATION.md § 6 for the full catalogue.                        */
/* ------------------------------------------------------------------------- */

// export const credits = {
//   async wallets() { return request("/api/v1/credits/wallets"); },
//   async ledger(limit = 100) { return request(`/api/v1/credits/ledger?limit=${limit}`); },
//   async consume(input: { feature_key: string; amount: string; reason?: string; reference: string }) {
//     return request("/api/v1/credits/consume", { method: "POST", body: input });
//   },
// };

// export const tenants = {
//   async children() { return request("/api/v1/tenants/children"); },
//   async create(input: { name: string; slug: string }) {
//     return request("/api/v1/tenants", { method: "POST", body: input });
//   },
// };

// export const users = {
//   async list() { return request("/api/v1/users"); },
//   async invite(input: { email: string; role_codes: string[] }) {
//     return request("/api/v1/users", { method: "POST", body: input });
//   },
// };

// export const plans = {
//   async list() { return request("/api/v1/plans", { skipAuth: true }); },
// };
