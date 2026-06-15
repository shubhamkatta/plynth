"""Lightweight request/response shapes as TypedDicts.

Kept hand-written from `docs/INTEGRATION.md` § 6 to avoid a pydantic
dependency. Generate from `docs/openapi.json` if you need exhaustive
coverage — datamodel-code-generator can target this file.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class Tokens(TypedDict):
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: str


# --- auth ---

class RegisterRequest(TypedDict, total=False):
    tenant_name: str
    tenant_slug: str
    email: str
    password: str
    full_name: str | None


class RegisterIndividualRequest(TypedDict, total=False):
    email: str
    password: str
    full_name: str | None


class LoginRequest(TypedDict, total=False):
    email: str
    password: str
    tenant_slug: str | None


class GoogleLoginRequest(TypedDict):
    code: str
    redirect_uri: str


class PasswordChangeRequest(TypedDict):
    current_password: str
    new_password: str


class ForgotPasswordRequest(TypedDict):
    email: str


class ForgotPasswordResponse(TypedDict, total=False):
    ok: bool
    reset_token: str | None
    expires_at: str | None


class ResetPasswordRequest(TypedDict):
    token: str
    new_password: str


class LogoutRequest(TypedDict, total=False):
    refresh_token: str | None
    all_sessions: bool


class MeResponse(TypedDict):
    id: str
    product_id: str
    tenant_id: str
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    permissions: list[str]


# --- tenants ---

TenantStatus = Literal["active", "suspended", "deactivated", "deleted"]
TenantType = Literal["company", "individual"]


class Tenant(TypedDict):
    id: str
    product_id: str
    name: str
    slug: str
    status: TenantStatus
    type: TenantType
    parent_id: str | None
    is_root: bool
    settings: dict[str, Any]
    expires_at: str | None
    created_at: str
    updated_at: str


class CreateTenantRequest(TypedDict, total=False):
    name: str
    slug: str
    type: TenantType
    parent_id: str | None
    settings: dict[str, Any]


class UpdateTenantRequest(TypedDict, total=False):
    name: str
    settings: dict[str, Any]
    expires_at: str | None


class AccessibleChild(TypedDict):
    id: str
    name: str
    slug: str
    status: TenantStatus
    can_act_as: bool
    reason: str | None


# --- users ---

class User(TypedDict):
    id: str
    product_id: str
    tenant_id: str
    email: str
    full_name: str | None
    is_active: bool
    is_verified: bool
    last_login_at: str | None
    created_at: str
    updated_at: str


class InviteUserRequest(TypedDict, total=False):
    email: str
    full_name: str | None
    role_codes: list[str]


class UpdateUserRequest(TypedDict, total=False):
    full_name: str | None
    email: str


# --- plans ---

PlanInterval = Literal["month", "year", "one_time"]


class PlanFeature(TypedDict):
    key: str
    display_name: str
    monthly_credits: str | None
    metadata: dict[str, Any]


class Plan(TypedDict):
    id: str
    product_id: str
    code: str
    name: str
    description: str | None
    price_amount: str
    price_currency: str
    interval: PlanInterval
    trial_days: int
    is_public: bool
    is_active: bool
    features: list[PlanFeature]
    metadata: dict[str, Any]


# --- subscription ---

SubscriptionStatus = Literal[
    "trial", "active", "past_due", "grace", "suspended", "cancelled", "expired"
]


class Subscription(TypedDict):
    id: str
    product_id: str
    tenant_id: str
    plan_id: str
    status: SubscriptionStatus
    current_period_start: str
    current_period_end: str
    trial_ends_at: str | None
    grace_ends_at: str | None
    cancelled_at: str | None
    provider: str
    provider_subscription_id: str | None


class PurchaseRequest(TypedDict, total=False):
    plan_code: str
    payment_method_id: str


class ChangeSubscriptionRequest(TypedDict, total=False):
    plan_code: str
    prorate: bool


class CancelSubscriptionRequest(TypedDict, total=False):
    at_period_end: bool


# --- credits ---

class CreditWallet(TypedDict):
    id: str
    product_id: str
    tenant_id: str
    feature_key: str
    balance: str
    monthly_grant: str | None
    updated_at: str


class CreditLedgerEntry(TypedDict):
    id: str
    product_id: str
    tenant_id: str
    wallet_id: str
    feature_key: str
    delta: str
    balance_after: str
    reason: str
    reference: str | None
    created_at: str


class ConsumeCreditsRequest(TypedDict, total=False):
    feature_key: str
    amount: str
    reason: str
    reference: str


class GrantCreditsRequest(TypedDict, total=False):
    tenant_id: str
    feature_key: str
    amount: str
    reason: str
    reference: str


# --- roles ---

class Role(TypedDict):
    id: str
    product_id: str
    code: str
    name: str
    description: str | None
    is_system: bool
    permission_codes: list[str]


class Permission(TypedDict):
    code: str
    description: str


class CreateRoleRequest(TypedDict, total=False):
    code: str
    name: str
    description: str | None
    permission_codes: list[str]


class UpdateRoleRequest(TypedDict, total=False):
    name: str
    description: str | None
    permission_codes: list[str]


class AssignRoleRequest(TypedDict, total=False):
    user_id: str
    role_code: str
    scope_tenant_id: str | None


# --- products (admin) ---

class Product(TypedDict):
    id: str
    slug: str
    name: str
    is_active: bool
    settings: dict[str, Any]
    created_at: str
    updated_at: str


class CreateProductRequest(TypedDict, total=False):
    slug: str
    name: str
    settings: dict[str, Any]


class UpdateProductRequest(TypedDict, total=False):
    name: str
    is_active: bool
    settings: dict[str, Any]


# --- env-vars vault (per-product, admin namespace) ---

class EnvVarSetRequest(TypedDict, total=False):
    value: str
    is_secret: bool
    description: str | None


class EnvVarPatchRequest(TypedDict, total=False):
    is_secret: bool
    description: str | None


class EnvVarListItem(TypedDict, total=False):
    key: str
    is_secret: bool
    description: str | None
    last_rotated_at: str
    preview: str | None
    value: str | None
    # True when the key matches the platform's server-only pattern
    # (e.g. GOOGLE_*_CLIENT_SECRET). Value stays in the vault but
    # is filtered out of the runtime GET /env response.
    is_server_only: bool


class EnvVarDetail(TypedDict):
    key: str
    value: str
    is_secret: bool
    description: str | None
    last_rotated_at: str
    created_at: str
    updated_at: str


# --- service tokens (per-product) ---

class ServiceTokenCreateRequest(TypedDict, total=False):
    name: str
    scopes: list[str]
    expires_at: str | None


class ServiceTokenResponse(TypedDict):
    id: str
    name: str
    scopes: list[str]
    expires_at: str | None
    revoked_at: str | None
    last_used_at: str | None
    last_used_ip: str | None
    created_at: str
    updated_at: str


class ServiceTokenIssued(ServiceTokenResponse):
    # Raw pst_… returned ONLY at creation — never echoed by list/get.
    token: str


# --- components (per-product feature modules) ---

class ComponentCreateRequest(TypedDict, total=False):
    code: str
    name: str
    description: str | None
    is_default_enabled: bool
    is_active: bool
    settings: dict[str, Any]
    # Plan codes whose subscribers receive this component. None = no
    # plan restriction. Non-empty list → other plans get is_enabled=False.
    required_plan_codes: list[str] | None


class ComponentUpdateRequest(TypedDict, total=False):
    name: str | None
    description: str | None
    is_default_enabled: bool
    is_active: bool
    settings: dict[str, Any]
    required_plan_codes: list[str] | None


class ComponentResponse(TypedDict):
    id: str
    code: str
    name: str
    description: str | None
    is_default_enabled: bool
    is_active: bool
    settings: dict[str, Any]
    required_plan_codes: list[str] | None
    created_at: str
    updated_at: str


class UserComponentOverrideRequest(TypedDict, total=False):
    is_enabled: bool
    reason: str | None


class UserComponentStatus(TypedDict, total=False):
    code: str
    name: str
    is_enabled: bool
    # "default" / "plan" / "tenant_override" / "override"
    source: str
    description: str | None
    reason: str | None
    # Set when source="plan": the codes the tenant would need to be on.
    required_plan_codes: list[str] | None


class TenantComponentOverrideRequest(TypedDict, total=False):
    is_enabled: bool
    reason: str | None


class TenantComponentStatus(TypedDict, total=False):
    code: str
    name: str
    is_enabled: bool
    # "default" / "plan" / "tenant_override"
    source: str
    description: str | None
    reason: str | None
    required_plan_codes: list[str] | None
