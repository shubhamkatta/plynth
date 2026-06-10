/**
 * Public types. Hand-written from docs/INTEGRATION.md § 6.
 * Re-generate from docs/openapi.json if you need exhaustive coverage.
 */

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_at: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

// --- auth ---

export interface RegisterRequest {
  tenant_name: string;
  tenant_slug: string;
  email: string;
  password: string;
  full_name?: string;
}

export interface RegisterIndividualRequest {
  email: string;
  password: string;
  full_name?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  tenant_slug?: string;
}

export interface GoogleLoginRequest {
  code: string;
  redirect_uri: string;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ForgotPasswordResponse {
  ok: boolean;
  reset_token?: string | null;
  expires_at?: string | null;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
}

export interface LogoutRequest {
  refresh_token?: string;
  all_sessions?: boolean;
}

export interface MeResponse {
  id: string;
  product_id: string;
  tenant_id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  permissions: string[];
  /** Map of active component code → access boolean. Empty if the
   * product hasn't declared any components yet. See § 6.5. */
  components: Record<string, boolean>;
}

// --- tenants ---

export type TenantStatus = "active" | "suspended" | "deactivated" | "deleted";
export type TenantType = "company" | "individual";

export interface Tenant {
  id: string;
  product_id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  type: TenantType;
  parent_id: string | null;
  is_root: boolean;
  settings: Record<string, unknown>;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTenantRequest {
  name: string;
  slug: string;
  type?: TenantType;
  parent_id?: string;
  settings?: Record<string, unknown>;
}

export interface UpdateTenantRequest {
  name?: string;
  settings?: Record<string, unknown>;
  expires_at?: string | null;
}

export interface AccessibleChild {
  id: string;
  name: string;
  slug: string;
  status: TenantStatus;
  can_act_as: boolean;
  reason: string | null;
}

// --- users ---

export interface User {
  id: string;
  product_id: string;
  tenant_id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InviteUserRequest {
  email: string;
  full_name?: string;
  role_codes?: string[];
}

export interface UpdateUserRequest {
  full_name?: string;
  email?: string;
}

// --- plans ---

export type PlanInterval = "month" | "year" | "one_time";

export interface PlanFeature {
  key: string;
  display_name: string;
  monthly_credits: string | null;
  metadata: Record<string, unknown>;
}

export interface Plan {
  id: string;
  product_id: string;
  code: string;
  name: string;
  description: string | null;
  price_amount: string;
  price_currency: string;
  interval: PlanInterval;
  trial_days: number;
  is_public: boolean;
  is_active: boolean;
  features: PlanFeature[];
  metadata: Record<string, unknown>;
}

// --- subscriptions ---

export type SubscriptionStatus =
  | "trial"
  | "active"
  | "past_due"
  | "grace"
  | "suspended"
  | "cancelled"
  | "expired";

export interface Subscription {
  id: string;
  product_id: string;
  tenant_id: string;
  plan_id: string;
  status: SubscriptionStatus;
  current_period_start: string;
  current_period_end: string;
  trial_ends_at: string | null;
  grace_ends_at: string | null;
  cancelled_at: string | null;
  provider: string;
  provider_subscription_id: string | null;
}

export interface PurchaseRequest {
  plan_code: string;
  payment_method_id?: string;
}

export interface ChangeSubscriptionRequest {
  plan_code: string;
  prorate?: boolean;
}

export interface CancelSubscriptionRequest {
  at_period_end?: boolean;
}

// --- credits ---

export interface CreditWallet {
  id: string;
  product_id: string;
  tenant_id: string;
  feature_key: string;
  balance: string;
  monthly_grant: string | null;
  updated_at: string;
}

export interface CreditLedgerEntry {
  id: string;
  product_id: string;
  tenant_id: string;
  wallet_id: string;
  feature_key: string;
  delta: string;
  balance_after: string;
  reason: string;
  reference: string | null;
  created_at: string;
}

export interface ConsumeCreditsRequest {
  feature_key: string;
  amount: string;
  reason?: string;
  reference?: string;
}

export interface GrantCreditsRequest {
  tenant_id: string;
  feature_key: string;
  amount: string;
  reason?: string;
  reference?: string;
}

// --- roles ---

export interface Role {
  id: string;
  product_id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permission_codes: string[];
}

export interface Permission {
  code: string;
  description: string;
}

export interface CreateRoleRequest {
  code: string;
  name: string;
  description?: string;
  permission_codes: string[];
}

export interface UpdateRoleRequest {
  name?: string;
  description?: string;
  permission_codes?: string[];
}

export interface AssignRoleRequest {
  user_id: string;
  role_code: string;
  scope_tenant_id?: string | null;
}

// --- products (admin) ---

export interface Product {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateProductRequest {
  slug: string;
  name: string;
  settings?: Record<string, unknown>;
}

export interface UpdateProductRequest {
  name?: string;
  is_active?: boolean;
  settings?: Record<string, unknown>;
}

// --- env vars (per-product vault, admin namespace) ---

export interface EnvVarSetRequest {
  value: string;
  is_secret?: boolean;
  description?: string;
}

export interface EnvVarPatchRequest {
  is_secret?: boolean;
  description?: string;
}

export interface EnvVarListItem {
  key: string;
  is_secret: boolean;
  description: string | null;
  last_rotated_at: string;
  /** Set for `is_secret: true` rows only. Looks like `sk_l…cdef`. */
  preview?: string | null;
  /** Set for `is_secret: false` rows only — full plaintext. */
  value?: string | null;
}

export interface EnvVarDetail {
  key: string;
  value: string;
  is_secret: boolean;
  description: string | null;
  last_rotated_at: string;
  created_at: string;
  updated_at: string;
}

// --- service tokens (per-product, used to call GET /env) ---

export interface ServiceTokenCreateRequest {
  name: string;
  scopes?: string[];
  expires_at?: string | null;
}

export interface ServiceTokenResponse {
  id: string;
  name: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  last_used_ip: string | null;
  created_at: string;
  updated_at: string;
}

export interface ServiceTokenIssued extends ServiceTokenResponse {
  /** The raw `pst_…` token. Returned ONLY at creation; never echoed by list/get. */
  token: string;
}

// --- components (per-product feature modules) ---

export interface ComponentCreateRequest {
  code: string;
  name: string;
  description?: string;
  is_default_enabled?: boolean;
  is_active?: boolean;
  settings?: Record<string, unknown>;
}

export interface ComponentUpdateRequest {
  name?: string;
  description?: string;
  is_default_enabled?: boolean;
  is_active?: boolean;
  settings?: Record<string, unknown>;
}

export interface ComponentResponse {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_default_enabled: boolean;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UserComponentOverrideRequest {
  is_enabled: boolean;
  reason?: string;
}

export interface UserComponentStatus {
  code: string;
  name: string;
  is_enabled: boolean;
  /** `"default"` = inherits `is_default_enabled`; `"override"` = explicit per-user row. */
  source: string;
  description?: string | null;
  reason?: string | null;
}
