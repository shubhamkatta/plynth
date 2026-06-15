import type { HttpClient } from "../http.js";
import type {
  ComponentCreateRequest,
  ComponentResponse,
  ComponentUpdateRequest,
  TenantComponentOverrideRequest,
  TenantComponentStatus,
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

  /**
   * Tenant-effective component listing for one tenant. Per-user overrides
   * are NOT consulted — this is the "what does Acme get" admin view.
   */
  async listTenant(slug: string, tenantId: string): Promise<TenantComponentStatus[]> {
    return this.http.request<TenantComponentStatus[]>({
      method: "GET",
      path: `/api/v1/admin/products/${slug}/components/tenants/${tenantId}`,
      asPlatformAdmin: true,
    });
  }

  /**
   * Set a per-tenant override. Grants or revokes a component for the
   * whole tenant — applied to every user in the tenant unless a per-user
   * override beats it. Use for ops grants ("give Acme this feature
   * without upgrading their plan").
   */
  async setTenantOverride(
    slug: string,
    tenantId: string,
    code: string,
    body: TenantComponentOverrideRequest,
  ): Promise<TenantComponentStatus> {
    return this.http.request<TenantComponentStatus>({
      method: "PUT",
      path: `/api/v1/admin/products/${slug}/components/tenants/${tenantId}/${code}`,
      body,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  /** Clear a per-tenant override — reverts to plan gate / default. */
  async clearTenantOverride(slug: string, tenantId: string, code: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/admin/products/${slug}/components/tenants/${tenantId}/${code}`,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }
}
