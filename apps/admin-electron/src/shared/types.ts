// Types shared between main, preload, and renderer processes.
// Keep this file free of node / electron imports — must be safe to ship to
// the renderer where Node APIs aren't available.

// ---------- generic API envelope -------------------------------------------

export interface ApiError {
  /** Stable machine-readable code, e.g. "not_found", "validation_failed" */
  code: string;
  message: string;
  details: Record<string, unknown>;
  /** HTTP status (0 if network / pre-flight failure) */
  status: number;
}

/** All IPC handlers wrap their return in this discriminated union so the
 *  renderer never has to try/catch — it branches on `.ok`. */
export type Result<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError };

// ---------- session ---------------------------------------------------------

/** Per-user session (regular login). Stored in keytar in the main process. */
export interface UserSession {
  accessToken:  string;
  refreshToken: string;
  expiresAt:    string;  // ISO timestamp from /auth/login
  email:        string;
  productSlug:  string;
}

/** Identity returned by /auth/me — what the renderer cares about. */
export interface MeResponse {
  id:          string;
  product_id:  string;
  tenant_id:   string;
  email:       string;
  full_name:   string | null;
  is_active:   boolean;
  is_verified: boolean;
  permissions: string[];
}

// ---------- product ---------------------------------------------------------

export type ProductStatus = "active" | "disabled" | "archived";

export interface Product {
  id:          string;
  slug:        string;
  name:        string;
  description: string | null;
  status:      ProductStatus;
  is_active:   boolean;
  settings:    Record<string, unknown>;
  created_at:  string;
  updated_at:  string;
}

export interface CreateProductPayload {
  name:         string;
  slug:         string;
  description?: string | null;
  settings?:    Record<string, unknown>;
}

// ---------- tenants ---------------------------------------------------------

export type TenantStatus = "active" | "suspended" | "deactivated" | "deleted";
export type TenantType   = "company" | "individual";

export interface Tenant {
  id:          string;
  product_id:  string;
  name:        string;
  slug:        string;
  status:      TenantStatus;
  type:        TenantType;
  parent_id:   string | null;
  is_root:     boolean;
  settings:    Record<string, unknown>;
  created_at:  string;
  updated_at:  string;
}

export interface CreateChildTenantPayload {
  name:       string;
  slug:       string;
  parent_id?: string | null;
  settings?:  Record<string, unknown>;
}

export interface UpdateTenantPayload {
  name?:     string;
  settings?: Record<string, unknown>;
}

// ---------- users -----------------------------------------------------------

export interface PlatformUser {
  id:           string;
  product_id:   string;
  tenant_id:    string;
  email:        string;
  full_name:    string | null;
  is_active:    boolean;
  is_verified:  boolean;
  created_at:   string;
  updated_at:   string;
}

export interface InviteUserPayload {
  email:           string;
  full_name?:      string | null;
  role_codes?:     string[];
  scope_tenant_id?: string | null;
}

export interface UpdateUserPayload {
  full_name?: string | null;
  is_active?: boolean;
}

// ---------- plans -----------------------------------------------------------

export type BillingInterval = "month" | "year" | "one_time";

export interface PlanFeature {
  id?:            string;
  feature_key:    string;
  limit_value?:   string | null;     // Decimal as string from API
  credit_amount?: string | null;
  is_hard_limit:  boolean;
  meta:           Record<string, unknown>;
}

export interface Plan {
  id:           string;
  code:         string;
  name:         string;
  description:  string | null;
  price_cents:  number;
  currency:     string;
  interval:     BillingInterval;
  trial_days:   number;
  is_public:    boolean;
  is_active:    boolean;
  features:     PlanFeature[];
  created_at:   string;
  updated_at:   string;
}

export interface CreatePlanPayload {
  code:          string;
  name:          string;
  description?:  string | null;
  price_cents:   number;
  currency?:     string;
  interval?:     BillingInterval;
  trial_days?:   number;
  is_public?:    boolean;
  features?:     Omit<PlanFeature, "id">[];
  provider_refs?: Record<string, unknown>;
}

export interface UpdatePlanPayload {
  name?:         string;
  description?:  string | null;
  price_cents?:  number;
  is_public?:    boolean;
  is_active?:    boolean;
  provider_refs?: Record<string, unknown>;
}

// ---------- roles -----------------------------------------------------------

export interface Role {
  id:          string;
  tenant_id:   string | null;
  name:        string;
  description: string | null;
  is_system:   boolean;
  permissions: string[];
  created_at:  string;
  updated_at:  string;
}

export interface CreateRolePayload {
  name:             string;
  description?:     string | null;
  permission_codes: string[];
}

export interface UpdateRolePayload {
  name?:             string;
  description?:      string | null;
  permission_codes?: string[];
}

export interface AssignRolePayload {
  user_id:          string;
  role_id:          string;
  scope_tenant_id?: string | null;
}

// ---------- subscriptions ---------------------------------------------------

export type SubscriptionStatus =
  | "trial" | "active" | "past_due" | "grace" | "suspended" | "cancelled";

export interface Subscription {
  id:                    string;
  tenant_id:             string;
  plan_id:               string;
  plan_code:             string;
  status:                SubscriptionStatus;
  current_period_start:  string;
  current_period_end:    string;
  trial_end:             string | null;
  grace_ends_at:         string | null;
  cancel_at_period_end:  boolean;
  cancelled_at:          string | null;
  has_access:            boolean;
  created_at:            string;
  updated_at:            string;
}

export interface PurchaseSubscriptionPayload {
  plan_code:             string;
  payment_method_token?: string | null;
}

export interface ChangeSubscriptionPayload {
  plan_code: string;
  proration: boolean;
}

export interface CancelSubscriptionPayload {
  at_period_end: boolean;
  reason?:       string | null;
}

// ---------- credits ---------------------------------------------------------

export type CreditEntryType =
  | "grant" | "debit" | "refund" | "expiry" | "adjustment";

export interface CreditWallet {
  id:          string;
  tenant_id:   string;
  feature_key: string;
  balance:     string;
  created_at:  string;
  updated_at:  string;
}

export interface CreditLedgerRow {
  id:            string;
  wallet_id:     string;
  entry_type:    CreditEntryType;
  amount:        string;
  balance_after: string;
  reason:        string | null;
  reference:     string | null;
  created_at:    string;
  updated_at:    string;
}

export interface GrantCreditPayload {
  feature_key: string;
  amount:      string;
  reason?:     string | null;
  reference?:  string | null;
}

// ---------- audit log -------------------------------------------------------

export interface AuditEntry {
  id:                       string;
  product_id:               string;
  tenant_id:                string;
  acting_from_tenant_id:    string | null;
  actor_user_id:            string | null;
  actor_ip:                 string | null;
  action:                   string;
  resource_type:            string | null;
  resource_id:              string | null;
  request_id:               string | null;
  diff:                     Record<string, unknown>;
  created_at:               string;
  updated_at:               string;
}

// ---------- IPC bridge surface ---------------------------------------------

/** The renderer accesses everything through `window.api`. This interface
 *  documents that surface; the preload script implements it; the renderer
 *  consumes it via the typed wrapper in `lib/api.ts`. */
export interface BridgeApi {
  auth: {
    loginAsUser:  (input: LoginInput)            => Promise<Result<UserSession>>;
    logout:       ()                             => Promise<Result<null>>;
    getSession:   ()                             => Promise<Result<UserSession | null>>;
    me:           ()                             => Promise<Result<MeResponse>>;
    setAdminToken: (token: string)               => Promise<Result<null>>;
    hasAdminToken: ()                            => Promise<Result<boolean>>;
    clearAdminToken: ()                          => Promise<Result<null>>;
  };
  products: {
    list:   ()                                   => Promise<Result<Product[]>>;
    create: (p: CreateProductPayload)            => Promise<Result<Product>>;
  };
  tenants: {
    list:        ()                              => Promise<Result<Tenant[]>>;
    createChild: (p: CreateChildTenantPayload)   => Promise<Result<Tenant>>;
    update:      (id: string, p: UpdateTenantPayload) => Promise<Result<Tenant>>;
    activate:    (id: string)                    => Promise<Result<Tenant>>;
    deactivate:  (id: string)                    => Promise<Result<Tenant>>;
  };
  users: {
    list:        ()                                          => Promise<Result<PlatformUser[]>>;
    invite:      (p: InviteUserPayload)                      => Promise<Result<PlatformUser>>;
    update:      (id: string, p: UpdateUserPayload)          => Promise<Result<PlatformUser>>;
    activate:    (id: string)                                => Promise<Result<PlatformUser>>;
    deactivate:  (id: string)                                => Promise<Result<PlatformUser>>;
    remove:      (id: string)                                => Promise<Result<null>>;
  };
  plans: {
    list:        ()                                          => Promise<Result<Plan[]>>;
    create:      (p: CreatePlanPayload)                      => Promise<Result<Plan>>;
    update:      (code: string, p: UpdatePlanPayload)        => Promise<Result<Plan>>;
  };
  roles: {
    list:        ()                                          => Promise<Result<Role[]>>;
    create:      (p: CreateRolePayload)                      => Promise<Result<Role>>;
    update:      (id: string, p: UpdateRolePayload)          => Promise<Result<Role>>;
    assign:      (p: AssignRolePayload)                      => Promise<Result<null>>;
    permissions: ()                                          => Promise<Result<string[]>>;
  };
  subscriptions: {
    get:         ()                                          => Promise<Result<Subscription>>;
    purchase:    (p: PurchaseSubscriptionPayload)            => Promise<Result<Subscription>>;
    change:      (p: ChangeSubscriptionPayload)              => Promise<Result<Subscription>>;
    cancel:      (p: CancelSubscriptionPayload)              => Promise<Result<Subscription>>;
  };
  credits: {
    wallets:     ()                                          => Promise<Result<CreditWallet[]>>;
    ledger:      (limit?: number)                            => Promise<Result<CreditLedgerRow[]>>;
    grant:       (p: GrantCreditPayload)                     => Promise<Result<CreditWallet>>;
  };
  audit: {
    list:   (query: AuditQuery)                  => Promise<Result<AuditEntry[]>>;
  };
  system: {
    baseUrl:             ()                          => Promise<Result<string>>;
    setBaseUrl:          (url: string)               => Promise<Result<null>>;
    openExternal:        (url: string)               => Promise<Result<null>>;
    adminProductSlug:    ()                          => Promise<Result<string | null>>;
    setAdminProductSlug: (slug: string | null)       => Promise<Result<null>>;
  };
}

export interface LoginInput {
  email:        string;
  password:     string;
  productSlug:  string;
  tenantSlug?:  string;
}

export interface AuditQuery {
  limit?:  number;
}

// ---------- global window typing -------------------------------------------

declare global {
  interface Window {
    api: BridgeApi;
  }
}
