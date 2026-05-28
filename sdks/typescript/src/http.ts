import type { TokenStore } from "./auth.js";
import { PlynthApiError, PlynthNetworkError, parseErrorResponse } from "./errors.js";
import type { Tokens } from "./types.js";

const API_PREFIX = "/api/v1";

export interface HttpConfig {
  baseUrl: string;
  productSlug?: string;
  adminToken?: string;
  actingTenantSlug?: string;
  tokenStore: TokenStore;
  fetch?: typeof fetch;
  uuid?: () => string;
}

export interface RequestOptions {
  method: string;
  path: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  productSlug?: string;
  actingTenantSlug?: string;
  asPlatformAdmin?: boolean;
  skipAuth?: boolean;
  idempotent?: boolean;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function isAdminPath(path: string): boolean {
  return path.startsWith(`${API_PREFIX}/admin/`);
}

function defaultUuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // RFC4122 v4 fallback
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export class HttpClient {
  readonly #cfg: HttpConfig;
  readonly #fetch: typeof fetch;
  readonly #uuid: () => string;

  constructor(cfg: HttpConfig) {
    this.#cfg = { ...cfg, baseUrl: cfg.baseUrl.replace(/\/+$/, "") };
    this.#fetch = cfg.fetch ?? globalThis.fetch.bind(globalThis);
    this.#uuid = cfg.uuid ?? defaultUuid;
  }

  async request<T>(opts: RequestOptions): Promise<T> {
    return this.#send<T>(opts, false);
  }

  async #send<T>(opts: RequestOptions, retried: boolean): Promise<T> {
    const headers = await this.#buildHeaders(opts);
    const url = this.#buildUrl(opts.path, opts.query);

    let res: Response;
    try {
      res = await this.#fetch(url, {
        method: opts.method,
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: opts.signal,
      });
    } catch (err) {
      throw new PlynthNetworkError(
        err instanceof Error ? err.message : String(err),
        err,
      );
    }

    const isUserCall = !opts.skipAuth && !opts.asPlatformAdmin && !isAdminPath(opts.path);
    if (res.status === 401 && isUserCall && !retried) {
      const tokens = await this.#cfg.tokenStore.get();
      if (tokens && (await this.#refresh(tokens))) {
        return this.#send<T>(opts, true);
      }
    }

    if (res.status === 204) return undefined as T;
    if (!res.ok) throw await parseErrorResponse(res);

    const text = await res.text();
    if (!text) return undefined as T;
    return JSON.parse(text) as T;
  }

  async #refresh(current: Tokens): Promise<boolean> {
    let res: Response;
    try {
      res = await this.#fetch(`${this.#cfg.baseUrl}${API_PREFIX}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
    } catch {
      await this.#cfg.tokenStore.clear();
      return false;
    }
    if (!res.ok) {
      await this.#cfg.tokenStore.clear();
      return false;
    }
    const next = (await res.json()) as Tokens;
    await this.#cfg.tokenStore.set(next);
    return true;
  }

  async #buildHeaders(opts: RequestOptions): Promise<Record<string, string>> {
    const headers: Record<string, string> = {
      Accept: "application/json",
    };
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";

    const wantAdmin = opts.asPlatformAdmin === true || isAdminPath(opts.path);

    if (wantAdmin) {
      if (!this.#cfg.adminToken) {
        throw new PlynthApiError(401, {
          code: "no_platform_admin_token",
          message: "Platform admin token not configured on client.",
          details: {},
        });
      }
      headers["X-Platform-Admin-Token"] = this.#cfg.adminToken;
    } else if (!opts.skipAuth) {
      const tokens = await this.#cfg.tokenStore.get();
      if (tokens) {
        headers["Authorization"] = `Bearer ${tokens.access_token}`;
      } else if (this.#cfg.adminToken && this.#cfg.productSlug) {
        // Admin god-mode: no session, admin token + default product configured.
        headers["X-Platform-Admin-Token"] = this.#cfg.adminToken;
      }
    }

    const slug = opts.productSlug ?? this.#cfg.productSlug;
    if (slug) headers["X-Product-Slug"] = slug;

    const acting = opts.actingTenantSlug ?? this.#cfg.actingTenantSlug;
    if (acting && !wantAdmin) headers["X-Acting-Tenant-Slug"] = acting;

    if (opts.idempotent || opts.idempotencyKey) {
      headers["Idempotency-Key"] = opts.idempotencyKey ?? this.#uuid();
    }

    return headers;
  }

  #buildUrl(path: string, query?: RequestOptions["query"]): string {
    const url = new URL(`${this.#cfg.baseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
      }
    }
    return url.toString();
  }
}
