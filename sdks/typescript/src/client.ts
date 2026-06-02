import { MemoryStore, type TokenStore } from "./auth.js";
import { HttpClient } from "./http.js";
import { AdminEnvResource } from "./resources/admin_env.js";
import { AuthResource } from "./resources/auth.js";
import { CreditsResource } from "./resources/credits.js";
import { EnvResource } from "./resources/env.js";
import { PlansResource } from "./resources/plans.js";
import { ProductsResource } from "./resources/products.js";
import { RolesResource } from "./resources/roles.js";
import { ServiceTokensResource } from "./resources/service_tokens.js";
import { SubscriptionResource } from "./resources/subscription.js";
import { TenantsResource } from "./resources/tenants.js";
import { UsersResource } from "./resources/users.js";

export interface PlynthClientOptions {
  baseUrl: string;
  productSlug?: string;
  adminToken?: string;
  /**
   * Per-product service token (`pst_…`) for the product-runtime
   * `client.env.fetch()` path. Never expose this to a browser /
   * mobile / Electron renderer.
   */
  serviceToken?: string;
  actingTenantSlug?: string;
  tokenStore?: TokenStore;
  fetch?: typeof fetch;
}

export class PlynthClient {
  readonly tokenStore: TokenStore;
  readonly auth: AuthResource;
  readonly tenants: TenantsResource;
  readonly users: UsersResource;
  readonly plans: PlansResource;
  readonly subscription: SubscriptionResource;
  readonly credits: CreditsResource;
  readonly roles: RolesResource;
  readonly products: ProductsResource;
  /** Admin: per-product env-vars vault CRUD. Uses platform admin token. */
  readonly adminEnv: AdminEnvResource;
  /** Admin: per-product service tokens. Uses platform admin token. */
  readonly serviceTokens: ServiceTokensResource;
  /** Product runtime: fetch this product's env vars. Uses `X-Service-Token`. */
  readonly env: EnvResource;

  constructor(opts: PlynthClientOptions) {
    this.tokenStore = opts.tokenStore ?? new MemoryStore();
    const http = new HttpClient({
      baseUrl: opts.baseUrl,
      productSlug: opts.productSlug,
      adminToken: opts.adminToken,
      serviceToken: opts.serviceToken,
      actingTenantSlug: opts.actingTenantSlug,
      tokenStore: this.tokenStore,
      fetch: opts.fetch,
    });
    this.auth = new AuthResource(http, this.tokenStore);
    this.tenants = new TenantsResource(http);
    this.users = new UsersResource(http);
    this.plans = new PlansResource(http);
    this.subscription = new SubscriptionResource(http);
    this.credits = new CreditsResource(http);
    this.roles = new RolesResource(http);
    this.products = new ProductsResource(http);
    this.adminEnv = new AdminEnvResource(http);
    this.serviceTokens = new ServiceTokensResource(http);
    this.env = new EnvResource(http);
  }
}
