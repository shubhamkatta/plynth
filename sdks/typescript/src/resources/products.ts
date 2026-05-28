import type { HttpClient } from "../http.js";
import type { CreateProductRequest, Product, UpdateProductRequest } from "../types.js";

export class ProductsResource {
  constructor(private readonly http: HttpClient) {}

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
