import type { HttpClient } from "../http.js";
import type { InviteUserRequest, UpdateUserRequest, User } from "../types.js";

export class UsersResource {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<User[]> {
    return this.http.request<User[]>({ method: "GET", path: "/api/v1/users" });
  }

  async invite(req: InviteUserRequest): Promise<User> {
    return this.http.request<User>({
      method: "POST",
      path: "/api/v1/users",
      body: req,
      idempotent: true,
    });
  }

  async update(userId: string, req: UpdateUserRequest): Promise<User> {
    return this.http.request<User>({
      method: "PATCH",
      path: `/api/v1/users/${userId}`,
      body: req,
      idempotent: true,
    });
  }

  async activate(userId: string): Promise<User> {
    return this.http.request<User>({
      method: "POST",
      path: `/api/v1/users/${userId}/activate`,
      idempotent: true,
    });
  }

  async deactivate(userId: string): Promise<User> {
    return this.http.request<User>({
      method: "POST",
      path: `/api/v1/users/${userId}/deactivate`,
      idempotent: true,
    });
  }

  async delete(userId: string): Promise<void> {
    await this.http.request<void>({
      method: "DELETE",
      path: `/api/v1/users/${userId}`,
      idempotent: true,
    });
  }
}
