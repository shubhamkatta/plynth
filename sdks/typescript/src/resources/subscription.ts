import type { HttpClient } from "../http.js";
import type {
  CancelSubscriptionRequest,
  ChangeSubscriptionRequest,
  PurchaseRequest,
  Subscription,
} from "../types.js";

export class SubscriptionResource {
  constructor(private readonly http: HttpClient) {}

  async get(): Promise<Subscription> {
    return this.http.request<Subscription>({ method: "GET", path: "/api/v1/subscription" });
  }

  async purchase(req: PurchaseRequest): Promise<Subscription> {
    return this.http.request<Subscription>({
      method: "POST",
      path: "/api/v1/subscription/purchase",
      body: req,
      idempotent: true,
    });
  }

  async change(req: ChangeSubscriptionRequest): Promise<Subscription> {
    return this.http.request<Subscription>({
      method: "POST",
      path: "/api/v1/subscription/change",
      body: req,
      idempotent: true,
    });
  }

  async cancel(req: CancelSubscriptionRequest = {}): Promise<Subscription> {
    return this.http.request<Subscription>({
      method: "POST",
      path: "/api/v1/subscription/cancel",
      body: req,
      idempotent: true,
    });
  }
}
