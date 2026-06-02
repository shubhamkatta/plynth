import type { HttpClient } from "../http.js";

/**
 * Product-runtime env fetch. Uses the `X-Service-Token` header — pass
 * the `serviceToken` to the `PlynthClient` constructor.
 *
 * Returns the decrypted vault as a flat `{KEY: value}` object. Cache
 * the result in your process; this endpoint is rate-limited and not
 * meant for per-request calls.
 */
export class EnvResource {
  constructor(private readonly http: HttpClient) {}

  async fetch(): Promise<Record<string, string>> {
    return this.http.request<Record<string, string>>({
      method: "GET",
      path: "/api/v1/env",
      asServiceToken: true,
    });
  }
}
