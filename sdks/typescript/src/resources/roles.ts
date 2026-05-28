import type { HttpClient } from "../http.js";
import type {
  AssignRoleRequest,
  CreateRoleRequest,
  Permission,
  Role,
  UpdateRoleRequest,
} from "../types.js";

export class RolesResource {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<Role[]> {
    return this.http.request<Role[]>({ method: "GET", path: "/api/v1/roles" });
  }

  async create(req: CreateRoleRequest): Promise<Role> {
    return this.http.request<Role>({
      method: "POST",
      path: "/api/v1/roles",
      body: req,
      idempotent: true,
    });
  }

  async update(roleId: string, req: UpdateRoleRequest): Promise<Role> {
    return this.http.request<Role>({
      method: "PATCH",
      path: `/api/v1/roles/${roleId}`,
      body: req,
      idempotent: true,
    });
  }

  async assign(req: AssignRoleRequest): Promise<void> {
    await this.http.request<void>({
      method: "POST",
      path: "/api/v1/roles/assign",
      body: req,
      idempotent: true,
    });
  }

  async permissions(): Promise<Permission[]> {
    return this.http.request<Permission[]>({
      method: "GET",
      path: "/api/v1/roles/permissions",
    });
  }
}
