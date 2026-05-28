import type { HttpClient } from "../http.js";
import type { Plan } from "../types.js";

export class PlansResource {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<Plan[]> {
    return this.http.request<Plan[]>({ method: "GET", path: "/api/v1/plans", skipAuth: true });
  }

  async create(req: Partial<Plan> & { code: string; name: string; price_amount: string }): Promise<Plan> {
    return this.http.request<Plan>({
      method: "POST",
      path: "/api/v1/plans",
      body: req,
      idempotent: true,
    });
  }

  async update(code: string, req: Partial<Plan>): Promise<Plan> {
    return this.http.request<Plan>({
      method: "PATCH",
      path: `/api/v1/plans/${code}`,
      body: req,
      idempotent: true,
    });
  }
}
