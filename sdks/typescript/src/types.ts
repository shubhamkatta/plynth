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
