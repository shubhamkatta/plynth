import type { HttpClient } from "../http.js";
import type {
  AccessibleChild,
  CreateTenantRequest,
  Tenant,
  UpdateTenantRequest,
} from "../types.js";

export class TenantsResource {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<Tenant[]> {
    return this.http.request<Tenant[]>({ method: "GET", path: "/api/v1/tenants" });
  }

  async create(req: CreateTenantRequest): Promise<Tenant> {
    return this.http.request<Tenant>({
      method: "POST",
      path: "/api/v1/tenants",
      body: req,
      idempotent: true,
    });
  }

  async children(): Promise<AccessibleChild[]> {
    return this.http.request<AccessibleChild[]>({
      method: "GET",
      path: "/api/v1/tenants/children",
    });
  }

  async update(tenantId: string, req: UpdateTenantRequest): Promise<Tenant> {
    return this.http.request<Tenant>({
      method: "PATCH",
      path: `/api/v1/tenants/${tenantId}`,
      body: req,
      idempotent: true,
    });
  }

  async activate(tenantId: string): Promise<Tenant> {
    return this.http.request<Tenant>({
      method: "POST",
      path: `/api/v1/tenants/${tenantId}/activate`,
      idempotent: true,
    });
  }

  async deactivate(tenantId: string): Promise<Tenant> {
    return this.http.request<Tenant>({
      method: "POST",
      path: `/api/v1/tenants/${tenantId}/deactivate`,
      idempotent: true,
    });
  }
}
