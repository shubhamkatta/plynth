import type { HttpClient } from "../http.js";
import type { CreateProductRequest, Product, UpdateProductRequest, Invite, ProspectInviteCreateRequest } from "../types.js";

export class ProductsResource {
  constructor(private readonly http: HttpClient) {}

  /**
   * Mint a PROSPECT invite: the invitee gets their own new tenant on accept.
   * Platform-admin token, not a user JWT.
   *
   * Pass `send_email: false` to get the link back without emailing it — which
   * is how invites are delivered while SES is still in the sandbox.
   */
  async createInvite(
    slug: string,
    req: ProspectInviteCreateRequest
  ): Promise<Invite> {
    return this.http.request<Invite>({
      method: "POST",
      path: `/api/v1/admin/products/${slug}/invites`,
      body: req,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  async list(): Promise<Product[]> {
    return this.http.request<Product[]>({
      method: "GET",
      path: "/api/v1/admin/products",
      asPlatformAdmin: true,
    });
  }

  async create(req: CreateProductRequest): Promise<Product> {
    return this.http.request<Product>({
      method: "POST",
      path: "/api/v1/admin/products",
      body: req,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }

  async update(slug: string, req: UpdateProductRequest): Promise<Product> {
    return this.http.request<Product>({
      method: "PATCH",
      path: `/api/v1/admin/products/${slug}`,
      body: req,
      asPlatformAdmin: true,
      idempotent: true,
    });
  }
}
