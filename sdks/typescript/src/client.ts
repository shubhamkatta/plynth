import { MemoryStore, type TokenStore } from "./auth.js";
import { HttpClient } from "./http.js";
import { AuthResource } from "./resources/auth.js";
import { CreditsResource } from "./resources/credits.js";
import { PlansResource } from "./resources/plans.js";
import { ProductsResource } from "./resources/products.js";
import { RolesResource } from "./resources/roles.js";
import { SubscriptionResource } from "./resources/subscription.js";
import { TenantsResource } from "./resources/tenants.js";
import { UsersResource } from "./resources/users.js";

export interface PlynthClientOptions {
  baseUrl: string;
  productSlug?: string;
  adminToken?: string;
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

  constructor(opts: PlynthClientOptions) {
    this.tokenStore = opts.tokenStore ?? new MemoryStore();
    const http = new HttpClient({
      baseUrl: opts.baseUrl,
      productSlug: opts.productSlug,
      adminToken: opts.adminToken,
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
  }
}
