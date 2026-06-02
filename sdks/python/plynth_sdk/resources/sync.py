"""Synchronous resource accessors. Thin wrappers around `PlynthClient.request`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

from plynth_sdk._http import RequestSpec
from plynth_sdk.types import (
    AccessibleChild,
    AssignRoleRequest,
    CancelSubscriptionRequest,
    ChangeSubscriptionRequest,
    ConsumeCreditsRequest,
    CreateProductRequest,
    CreateRoleRequest,
    CreateTenantRequest,
    CreditLedgerEntry,
    CreditWallet,
    EnvVarDetail,
    EnvVarListItem,
    EnvVarPatchRequest,
    EnvVarSetRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleLoginRequest,
    GrantCreditsRequest,
    InviteUserRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    PasswordChangeRequest,
    Permission,
    Plan,
    Product,
    PurchaseRequest,
    RegisterIndividualRequest,
    RegisterRequest,
    ResetPasswordRequest,
    Role,
    ServiceTokenCreateRequest,
    ServiceTokenIssued,
    ServiceTokenResponse,
    Subscription,
    Tenant,
    Tokens,
    UpdateProductRequest,
    UpdateRoleRequest,
    UpdateTenantRequest,
    UpdateUserRequest,
    User,
)

if TYPE_CHECKING:
    from plynth_sdk.client import PlynthClient


class _Base:
    def __init__(self, client: PlynthClient) -> None:
        self._c = client


class AuthResource(_Base):
    def register(self, req: RegisterRequest) -> Tokens:
        tokens: Tokens = self._c.request(
            RequestSpec("POST", "/api/v1/auth/register", json_body=dict(req), skip_auth=True, idempotent=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    def register_individual(self, req: RegisterIndividualRequest) -> Tokens:
        tokens: Tokens = self._c.request(
            RequestSpec("POST", "/api/v1/auth/register-individual", json_body=dict(req), skip_auth=True, idempotent=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    def login(self, req: LoginRequest) -> Tokens:
        tokens: Tokens = self._c.request(
            RequestSpec("POST", "/api/v1/auth/login", json_body=dict(req), skip_auth=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    def google(self, req: GoogleLoginRequest) -> Tokens:
        tokens: Tokens = self._c.request(
            RequestSpec("POST", "/api/v1/auth/google", json_body=dict(req), skip_auth=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    def logout(self, req: LogoutRequest | None = None) -> None:
        cur = self._c.token_store.get()
        body: dict[str, Any] = dict(req or {})
        body.setdefault("refresh_token", cur["refresh_token"] if cur else None)
        self._c.request(RequestSpec("POST", "/api/v1/auth/logout", json_body=body))
        self._c.token_store.clear()

    def me(self) -> MeResponse:
        return self._c.request(RequestSpec("GET", "/api/v1/auth/me"))

    def change_password(self, req: PasswordChangeRequest) -> None:
        self._c.request(RequestSpec("POST", "/api/v1/auth/password", json_body=dict(req)))

    def forgot_password(self, req: ForgotPasswordRequest) -> ForgotPasswordResponse:
        return self._c.request(
            RequestSpec("POST", "/api/v1/auth/password/forgot", json_body=dict(req), skip_auth=True)
        )

    def reset_password(self, req: ResetPasswordRequest) -> None:
        self._c.request(
            RequestSpec("POST", "/api/v1/auth/password/reset", json_body=dict(req), skip_auth=True)
        )


class TenantsResource(_Base):
    def list(self) -> List[Tenant]:
        return self._c.request(RequestSpec("GET", "/api/v1/tenants"))

    def create(self, req: CreateTenantRequest) -> Tenant:
        return self._c.request(RequestSpec("POST", "/api/v1/tenants", json_body=dict(req), idempotent=True))

    def children(self) -> List[AccessibleChild]:
        return self._c.request(RequestSpec("GET", "/api/v1/tenants/children"))

    def update(self, tenant_id: str, req: UpdateTenantRequest) -> Tenant:
        return self._c.request(
            RequestSpec("PATCH", f"/api/v1/tenants/{tenant_id}", json_body=dict(req), idempotent=True)
        )

    def activate(self, tenant_id: str) -> Tenant:
        return self._c.request(RequestSpec("POST", f"/api/v1/tenants/{tenant_id}/activate", idempotent=True))

    def deactivate(self, tenant_id: str) -> Tenant:
        return self._c.request(RequestSpec("POST", f"/api/v1/tenants/{tenant_id}/deactivate", idempotent=True))


class UsersResource(_Base):
    def list(self) -> List[User]:
        return self._c.request(RequestSpec("GET", "/api/v1/users"))

    def invite(self, req: InviteUserRequest) -> User:
        return self._c.request(RequestSpec("POST", "/api/v1/users", json_body=dict(req), idempotent=True))

    def update(self, user_id: str, req: UpdateUserRequest) -> User:
        return self._c.request(
            RequestSpec("PATCH", f"/api/v1/users/{user_id}", json_body=dict(req), idempotent=True)
        )

    def activate(self, user_id: str) -> User:
        return self._c.request(RequestSpec("POST", f"/api/v1/users/{user_id}/activate", idempotent=True))

    def deactivate(self, user_id: str) -> User:
        return self._c.request(RequestSpec("POST", f"/api/v1/users/{user_id}/deactivate", idempotent=True))

    def delete(self, user_id: str) -> None:
        self._c.request(RequestSpec("DELETE", f"/api/v1/users/{user_id}", idempotent=True))


class PlansResource(_Base):
    def list(self) -> List[Plan]:
        return self._c.request(RequestSpec("GET", "/api/v1/plans", skip_auth=True))

    def create(self, req: dict[str, Any]) -> Plan:
        return self._c.request(RequestSpec("POST", "/api/v1/plans", json_body=req, idempotent=True))

    def update(self, code: str, req: dict[str, Any]) -> Plan:
        return self._c.request(
            RequestSpec("PATCH", f"/api/v1/plans/{code}", json_body=req, idempotent=True)
        )


class SubscriptionResource(_Base):
    def get(self) -> Subscription:
        return self._c.request(RequestSpec("GET", "/api/v1/subscription"))

    def purchase(self, req: PurchaseRequest) -> Subscription:
        return self._c.request(
            RequestSpec("POST", "/api/v1/subscription/purchase", json_body=dict(req), idempotent=True)
        )

    def change(self, req: ChangeSubscriptionRequest) -> Subscription:
        return self._c.request(
            RequestSpec("POST", "/api/v1/subscription/change", json_body=dict(req), idempotent=True)
        )

    def cancel(self, req: CancelSubscriptionRequest | None = None) -> Subscription:
        return self._c.request(
            RequestSpec("POST", "/api/v1/subscription/cancel", json_body=dict(req or {}), idempotent=True)
        )


class CreditsResource(_Base):
    def wallets(self) -> List[CreditWallet]:
        return self._c.request(RequestSpec("GET", "/api/v1/credits/wallets"))

    def ledger(self, *, limit: int | None = None, cursor: str | None = None) -> List[CreditLedgerEntry]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        return self._c.request(RequestSpec("GET", "/api/v1/credits/ledger", params=params or None))

    def consume(self, req: ConsumeCreditsRequest) -> CreditWallet:
        return self._c.request(
            RequestSpec("POST", "/api/v1/credits/consume", json_body=dict(req), idempotent=True)
        )

    def grant(self, req: GrantCreditsRequest) -> CreditWallet:
        return self._c.request(
            RequestSpec("POST", "/api/v1/credits/grant", json_body=dict(req), idempotent=True)
        )


class RolesResource(_Base):
    def list(self) -> List[Role]:
        return self._c.request(RequestSpec("GET", "/api/v1/roles"))

    def create(self, req: CreateRoleRequest) -> Role:
        return self._c.request(RequestSpec("POST", "/api/v1/roles", json_body=dict(req), idempotent=True))

    def update(self, role_id: str, req: UpdateRoleRequest) -> Role:
        return self._c.request(
            RequestSpec("PATCH", f"/api/v1/roles/{role_id}", json_body=dict(req), idempotent=True)
        )

    def assign(self, req: AssignRoleRequest) -> None:
        self._c.request(RequestSpec("POST", "/api/v1/roles/assign", json_body=dict(req), idempotent=True))

    def permissions(self) -> List[Permission]:
        return self._c.request(RequestSpec("GET", "/api/v1/roles/permissions"))


class ProductsResource(_Base):
    def list(self) -> List[Product]:
        return self._c.request(RequestSpec("GET", "/api/v1/admin/products", as_platform_admin=True))

    def create(self, req: CreateProductRequest) -> Product:
        return self._c.request(
            RequestSpec(
                "POST",
                "/api/v1/admin/products",
                json_body=dict(req),
                as_platform_admin=True,
                idempotent=True,
            )
        )

    def update(self, slug: str, req: UpdateProductRequest) -> Product:
        return self._c.request(
            RequestSpec(
                "PATCH",
                f"/api/v1/admin/products/{slug}",
                json_body=dict(req),
                as_platform_admin=True,
                idempotent=True,
            )
        )


class AdminEnvResource(_Base):
    """Admin: per-product env-vars vault CRUD. Uses platform admin token."""

    def list(self, slug: str) -> List[EnvVarListItem]:
        return self._c.request(
            RequestSpec("GET", f"/api/v1/admin/products/{slug}/env",
                        as_platform_admin=True)
        )

    def set(self, slug: str, key: str, req: EnvVarSetRequest) -> EnvVarListItem:
        return self._c.request(
            RequestSpec("PUT", f"/api/v1/admin/products/{slug}/env/{key}",
                        json_body=dict(req),
                        as_platform_admin=True, idempotent=True)
        )

    def patch(self, slug: str, key: str, req: EnvVarPatchRequest) -> EnvVarListItem:
        return self._c.request(
            RequestSpec("PATCH", f"/api/v1/admin/products/{slug}/env/{key}",
                        json_body=dict(req),
                        as_platform_admin=True, idempotent=True)
        )

    def reveal(self, slug: str, key: str, reason: str) -> EnvVarDetail:
        return self._c.request(
            RequestSpec("GET", f"/api/v1/admin/products/{slug}/env/{key}",
                        params={"reveal": True, "reason": reason},
                        as_platform_admin=True)
        )

    def delete(self, slug: str, key: str) -> None:
        self._c.request(
            RequestSpec("DELETE", f"/api/v1/admin/products/{slug}/env/{key}",
                        as_platform_admin=True, idempotent=True)
        )


class ServiceTokensResource(_Base):
    """Admin: per-product service tokens. Returns raw `pst_…` ONCE on issue."""

    def issue(self, slug: str, req: ServiceTokenCreateRequest) -> ServiceTokenIssued:
        return self._c.request(
            RequestSpec("POST", f"/api/v1/admin/products/{slug}/service-tokens",
                        json_body=dict(req),
                        as_platform_admin=True, idempotent=True)
        )

    def list(self, slug: str) -> List[ServiceTokenResponse]:
        return self._c.request(
            RequestSpec("GET", f"/api/v1/admin/products/{slug}/service-tokens",
                        as_platform_admin=True)
        )

    def revoke(self, slug: str, token_id: str) -> None:
        self._c.request(
            RequestSpec("DELETE", f"/api/v1/admin/products/{slug}/service-tokens/{token_id}",
                        as_platform_admin=True, idempotent=True)
        )


class EnvResource(_Base):
    """Product-runtime: fetch the calling product's env vars (X-Service-Token)."""

    def fetch(self) -> dict[str, str]:
        return self._c.request(
            RequestSpec("GET", "/api/v1/env", as_service_token=True)
        )
