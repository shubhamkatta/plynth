import type { HttpClient } from "../http.js";
import type {
  ComponentCreateRequest,
  ComponentResponse,
  ComponentUpdateRequest,
} from "../types.js";

/**
 * Admin namespace for the per-product component catalog. Uses the
 * platform admin token. Slug per-call so one client manages many.
 */
export class AdminComponentsResource {
  constructor(private readonly http: HttpClient) {}

  /** List ALL components for the product, including inactive ones. */
  async list(slug: string): Promise<ComponentResponse[]> {
    return this.http.request<ComponentResponse[]>({
      method: "GET",
      path: `/api/v1/admin/products/${slug}/components`,
      asPlatformAdmin: true,
    });
  }

  async create(slug: string, body: ComponentCreateRequest): Promise<ComponentResponse> {
    return this.http.request<ComponentResponse>({
      method: "POST",
      path: `/api/v1/admin/products/${slug}/components`,
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  async update(slug: string, code: string, body: ComponentUpdateRequest): Promise<ComponentResponse> {
    return this.http.request<ComponentResponse>({
      method: "PATCH",
      path: `/api/v1/admin/products/${slug}/components/${code}`,
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  async delete(slug: string, code: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/admin/products/${slug}/components/${code}`,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }
}
