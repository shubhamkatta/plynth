import type { HttpClient } from "../http.js";
import type {
  UserComponentOverrideRequest,
  UserComponentStatus,
} from "../types.js";

/**
 * User-facing components surface:
 * - `list()`           — what's available to the calling user
 * - `listForUser(id)`  — what's available to another user in the same
 *                        tenant (RBAC `components:read`)
 * - `setOverride(...)` — enable/disable for a specific user (RBAC
 *                        `components:override`)
 * - `clearOverride(...)` — revert to component default
 */
export class ComponentsResource {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<UserComponentStatus[]> {
    return this.http.request<UserComponentStatus[]>({
      method: "GET",
      path: "/api/v1/components",
    });
  }

  async listForUser(userId: string): Promise<UserComponentStatus[]> {
    return this.http.request<UserComponentStatus[]>({
      method: "GET",
      path: `/api/v1/users/${userId}/components`,
    });
  }

  async setOverride(
    userId: string,
    code: string,
    body: UserComponentOverrideRequest,
  ): Promise<UserComponentStatus> {
    return this.http.request<UserComponentStatus>({
      method: "PUT",
      path: `/api/v1/users/${userId}/components/${code}`,
      body,
      idempotent: true,
    });
  }

  async clearOverride(userId: string, code: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/users/${userId}/components/${code}`,
      idempotent: true,
    });
  }
}
