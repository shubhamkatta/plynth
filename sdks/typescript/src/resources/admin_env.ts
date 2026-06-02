import type { HttpClient } from "../http.js";
import type {
  EnvVarDetail,
  EnvVarListItem,
  EnvVarPatchRequest,
  EnvVarSetRequest,
} from "../types.js";

/**
 * Admin namespace for the per-product env-vars vault. All methods use
 * the platform admin token. Slug is passed per-call so one client can
 * manage multiple products.
 */
export class AdminEnvResource {
  constructor(private readonly http: HttpClient) {}

  async list(slug: string): Promise<EnvVarListItem[]> {
    return this.http.request<EnvVarListItem[]>({
      method: "GET",
      path: `/api/v1/admin/products/${slug}/env`,
      asPlatformAdmin: true,
    });
  }

  /** Create or rotate (idempotent on key). Always stamps `last_rotated_at`. */
  async set(slug: string, key: string, body: EnvVarSetRequest): Promise<EnvVarListItem> {
    return this.http.request<EnvVarListItem>({
      method: "PUT",
      path: `/api/v1/admin/products/${slug}/env/${key}`,
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  /** Patch metadata only (`is_secret`, `description`). Does NOT rotate. */
  async patch(slug: string, key: string, body: EnvVarPatchRequest): Promise<EnvVarListItem> {
    return this.http.request<EnvVarListItem>({
      method: "PATCH",
      path: `/api/v1/admin/products/{slug}/env/{key}`.replace("{slug}", slug).replace("{key}", key),
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  /**
   * Reveal plaintext for one var. Writes a high-severity audit row with
   * the operator-supplied `reason`. `reason` must be 3-255 chars.
   */
  async reveal(slug: string, key: string, reason: string): Promise<EnvVarDetail> {
    return this.http.request<EnvVarDetail>({
      method: "GET",
      path: `/api/v1/admin/products/${slug}/env/${key}`,
      query: { reveal: true, reason },
      asPlatformAdmin: true,
    });
  }

  async delete(slug: string, key: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/admin/products/${slug}/env/${key}`,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }
}
