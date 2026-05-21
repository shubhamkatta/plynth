// Single HTTP client used by every main-process handler. Knows the platform
// base URL, X-Product-Slug + Authorization headers, idempotency keys, error
// envelope, and the 401-refresh-and-retry-once dance.
//
// Anything the user can do from the platform's Postman collection is reachable
// from here via `call(method, path, opts)`.

import { randomUUID } from "node:crypto";
import log from "electron-log/main";
import type { ApiError } from "@shared/types";
import { getConfig } from "@main/config";
import {
  clearSession,
  loadAdminToken,
  loadSession,
  saveSession,
} from "@main/api/secrets";

/** Path prefixes that are inherently cross-product and must use the
 *  platform-admin token (never a user JWT). The token gates them server-side. */
const PLATFORM_ADMIN_PATHS = ["/api/v1/admin/"];

function isPlatformAdminPath(path: string): boolean {
  return PLATFORM_ADMIN_PATHS.some(p => path.startsWith(p));
}

export interface CallOpts {
  /** JSON body — auto-stringified. */
  body?: unknown;
  /** Override product slug. Defaults to the slug saved in the current session. */
  productSlug?: string;
  /** Act-as a child tenant for this request. */
  actingTenantSlug?: string;
  /** Skip auth header (use for /auth/register, /auth/login, /auth/refresh). */
  skipAuth?: boolean;
  /** Use the platform admin token instead of the user JWT. */
  asPlatformAdmin?: boolean;
  /** Idempotency-Key header. Auto-generated if `idempotent` is true and no
   *  explicit key is given. */
  idempotencyKey?: string;
  idempotent?: boolean;
  /** Already retried after refresh — prevents infinite loop. */
  _retried?: boolean;
}

export class HttpError extends Error implements ApiError {
  code:    string;
  details: Record<string, unknown>;
  status:  number;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status  = status;
    this.code    = code;
    this.details = details;
  }
}

async function buildHeaders(opts: CallOpts, path: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
  };

  const session    = opts.skipAuth ? null : await loadSession();
  const adminToken = await loadAdminToken();
  const cfg        = getConfig();

  // Auth selection order (highest priority first):
  //   1. Explicit asPlatformAdmin or platform-admin-only path → admin token.
  //   2. User session → JWT bearer.
  //   3. No session but admin token + configured admin product → admin god-mode.
  //   4. None of the above → no auth header (login routes set skipAuth: true).
  const wantAdmin    = opts.asPlatformAdmin || isPlatformAdminPath(path);
  const adminGodMode = !wantAdmin && !session && adminToken && cfg.adminProductSlug;

  if (wantAdmin) {
    if (!adminToken) {
      throw new HttpError(401, "no_platform_admin_token",
        "Platform admin token not configured. Set it in Settings.");
    }
    headers["X-Platform-Admin-Token"] = adminToken;
  } else if (session) {
    headers["Authorization"] = `Bearer ${session.accessToken}`;
  } else if (adminGodMode) {
    headers["X-Platform-Admin-Token"] = adminToken!;
  }

  // Product slug — explicit > session > admin context. Admin-only paths
  // (/api/v1/admin/*) don't need one.
  const productSlug =
    opts.productSlug
    ?? session?.productSlug
    ?? (adminGodMode ? cfg.adminProductSlug ?? undefined : undefined);
  if (productSlug && !wantAdmin) {
    headers["X-Product-Slug"] = productSlug;
  } else if (productSlug && wantAdmin && opts.productSlug) {
    // Caller explicitly asked for a product slug alongside admin token —
    // some endpoints accept both (e.g. seeding plans for a fresh product).
    headers["X-Product-Slug"] = productSlug;
  }

  // Explicit per-call override beats the global picker.
  const actingTenant = opts.actingTenantSlug ?? cfg.actingTenantSlug;
  if (actingTenant && !wantAdmin) {
    // Admin-only paths (/api/v1/admin/*) don't have a tenant context.
    headers["X-Acting-Tenant-Slug"] = actingTenant;
  }

  if (opts.idempotent || opts.idempotencyKey) {
    headers["Idempotency-Key"] = opts.idempotencyKey ?? randomUUID();
  }

  return headers;
}

async function refreshAccessToken(): Promise<boolean> {
  const session = await loadSession();
  if (!session) return false;
  try {
    const r = await fetch(`${getConfig().baseUrl}/api/v1/auth/refresh`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ refresh_token: session.refreshToken }),
    });
    if (!r.ok) {
      log.warn("client.refresh_failed", { status: r.status });
      await clearSession();
      return false;
    }
    const next = await r.json();
    await saveSession({
      ...session,
      accessToken:  next.access_token,
      refreshToken: next.refresh_token,
      expiresAt:    next.expires_at,
    });
    log.info("client.refresh_ok");
    return true;
  } catch (err) {
    log.error("client.refresh_threw", err);
    await clearSession();
    return false;
  }
}

export async function call<T = unknown>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path:   string,
  opts:   CallOpts = {},
): Promise<T> {
  const { baseUrl } = getConfig();
  const url     = `${baseUrl}${path}`;
  const headers = await buildHeaders(opts, path);
  const init: RequestInit = { method, headers };
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body);

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    log.error("client.network_error", { method, path, err: String(err) });
    throw new HttpError(0, "network_error", err instanceof Error ? err.message : String(err));
  }

  // 401 on a user-auth call → try refresh once, then retry the original.
  if (res.status === 401 && !opts.skipAuth && !opts.asPlatformAdmin && !opts._retried) {
    if (await refreshAccessToken()) {
      return call<T>(method, path, { ...opts, _retried: true });
    }
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    if (!res.ok) {
      throw new HttpError(res.status, "http_error", res.statusText);
    }
    return undefined as T;
  }

  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try { parsed = JSON.parse(text); }
    catch { parsed = { code: "parse_error", message: text, details: {} }; }
  }

  if (!res.ok) {
    const body = parsed as Partial<ApiError> | null;
    throw new HttpError(
      res.status,
      body?.code    ?? "http_error",
      body?.message ?? res.statusText,
      body?.details ?? {},
    );
  }

  return parsed as T;
}
