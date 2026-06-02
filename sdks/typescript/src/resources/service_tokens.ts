import type { HttpClient } from "../http.js";
import type {
  ServiceTokenCreateRequest,
  ServiceTokenIssued,
  ServiceTokenResponse,
} from "../types.js";

/**
 * Admin namespace for per-product service tokens. The raw `pst_…`
 * token is in the response only at `issue()` time; the platform stores
 * SHA-256 only.
 */
export class ServiceTokensResource {
  constructor(private readonly http: HttpClient) {}

  async issue(slug: string, body: ServiceTokenCreateRequest): Promise<ServiceTokenIssued> {
    return this.http.request<ServiceTokenIssued>({
      method: "POST",
      path: `/api/v1/admin/products/${slug}/service-tokens`,
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  async list(slug: string): Promise<ServiceTokenResponse[]> {
    return this.http.request<ServiceTokenResponse[]>({
      method: "GET",
      path: `/api/v1/admin/products/${slug}/service-tokens`,
      asPlatformAdmin: true,
    });
  }

  async revoke(slug: string, tokenId: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/admin/products/${slug}/service-tokens/${tokenId}`,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }
}
