"""Async resource accessors. Mirror plynth_sdk.resources.sync exactly."""

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
    from plynth_sdk.async_client import AsyncPlynthClient


class _Base:
    def __init__(self, client: AsyncPlynthClient) -> None:
        self._c = client


class AuthResource(_Base):
    async def register(self, req: RegisterRequest) -> Tokens:
        tokens: Tokens = await self._c.request(
            RequestSpec("POST", "/api/v1/auth/register", json_body=dict(req), skip_auth=True, idempotent=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    async def register_individual(self, req: RegisterIndividualRequest) -> Tokens:
        tokens: Tokens = await self._c.request(
            RequestSpec("POST", "/api/v1/auth/register-individual", json_body=dict(req), skip_auth=True, idempotent=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    async def login(self, req: LoginRequest) -> Tokens:
        tokens: Tokens = await self._c.request(
            RequestSpec("POST", "/api/v1/auth/login", json_body=dict(req), skip_auth=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    async def google(self, req: GoogleLoginRequest) -> Tokens:
        tokens: Tokens = await self._c.request(
            RequestSpec("POST", "/api/v1/auth/google", json_body=dict(req), skip_auth=True)
        )
        self._c.token_store.set(tokens)
        return tokens

    async def logout(self, req: LogoutRequest | None = None) -> None:
        cur = self._c.token_store.get()
        body: dict[str, Any] = dict(req or {})
        body.setdefault("refresh_token", cur["refresh_token"] if cur else None)
        await self._c.request(RequestSpec("POST", "/api/v1/auth/logout", json_body=body))
        self._c.token_store.clear()

    async def me(self) -> MeResponse:
        return await self._c.request(RequestSpec("GET", "/api/v1/auth/me"))

    async def change_password(self, req: PasswordChangeRequest) -> None:
        await self._c.request(RequestSpec("POST", "/api/v1/auth/password", json_body=dict(req)))

    async def forgot_password(self, req: ForgotPasswordRequest) -> ForgotPasswordResponse:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/auth/password/forgot", json_body=dict(req), skip_auth=True)
        )

    async def reset_password(self, req: ResetPasswordRequest) -> None:
        await self._c.request(
            RequestSpec("POST", "/api/v1/auth/password/reset", json_body=dict(req), skip_auth=True)
        )


class TenantsResource(_Base):
    async def list(self) -> List[Tenant]:
        return await self._c.request(RequestSpec("GET", "/api/v1/tenants"))

    async def create(self, req: CreateTenantRequest) -> Tenant:
        return await self._c.request(RequestSpec("POST", "/api/v1/tenants", json_body=dict(req), idempotent=True))

    async def children(self) -> List[AccessibleChild]:
        return await self._c.request(RequestSpec("GET", "/api/v1/tenants/children"))

    async def update(self, tenant_id: str, req: UpdateTenantRequest) -> Tenant:
        return await self._c.request(
            RequestSpec("PATCH", f"/api/v1/tenants/{tenant_id}", json_body=dict(req), idempotent=True)
        )

    async def activate(self, tenant_id: str) -> Tenant:
        return await self._c.request(RequestSpec("POST", f"/api/v1/tenants/{tenant_id}/activate", idempotent=True))

    async def deactivate(self, tenant_id: str) -> Tenant:
        return await self._c.request(RequestSpec("POST", f"/api/v1/tenants/{tenant_id}/deactivate", idempotent=True))


class UsersResource(_Base):
    async def list(self) -> List[User]:
        return await self._c.request(RequestSpec("GET", "/api/v1/users"))

    async def invite(self, req: InviteUserRequest) -> User:
        return await self._c.request(RequestSpec("POST", "/api/v1/users", json_body=dict(req), idempotent=True))

    async def update(self, user_id: str, req: UpdateUserRequest) -> User:
        return await self._c.request(
            RequestSpec("PATCH", f"/api/v1/users/{user_id}", json_body=dict(req), idempotent=True)
        )

    async def activate(self, user_id: str) -> User:
        return await self._c.request(RequestSpec("POST", f"/api/v1/users/{user_id}/activate", idempotent=True))

    async def deactivate(self, user_id: str) -> User:
        return await self._c.request(RequestSpec("POST", f"/api/v1/users/{user_id}/deactivate", idempotent=True))

    async def delete(self, user_id: str) -> None:
        await self._c.request(RequestSpec("DELETE", f"/api/v1/users/{user_id}", idempotent=True))


class PlansResource(_Base):
    async def list(self) -> List[Plan]:
        return await self._c.request(RequestSpec("GET", "/api/v1/plans", skip_auth=True))

    async def create(self, req: dict[str, Any]) -> Plan:
        return await self._c.request(RequestSpec("POST", "/api/v1/plans", json_body=req, idempotent=True))

    async def update(self, code: str, req: dict[str, Any]) -> Plan:
        return await self._c.request(
            RequestSpec("PATCH", f"/api/v1/plans/{code}", json_body=req, idempotent=True)
        )


class SubscriptionResource(_Base):
    async def get(self) -> Subscription:
        return await self._c.request(RequestSpec("GET", "/api/v1/subscription"))

    async def purchase(self, req: PurchaseRequest) -> Subscription:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/subscription/purchase", json_body=dict(req), idempotent=True)
        )

    async def change(self, req: ChangeSubscriptionRequest) -> Subscription:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/subscription/change", json_body=dict(req), idempotent=True)
        )

    async def cancel(self, req: CancelSubscriptionRequest | None = None) -> Subscription:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/subscription/cancel", json_body=dict(req or {}), idempotent=True)
        )


class CreditsResource(_Base):
    async def wallets(self) -> List[CreditWallet]:
        return await self._c.request(RequestSpec("GET", "/api/v1/credits/wallets"))

    async def ledger(self, *, limit: int | None = None, cursor: str | None = None) -> List[CreditLedgerEntry]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        return await self._c.request(RequestSpec("GET", "/api/v1/credits/ledger", params=params or None))

    async def consume(self, req: ConsumeCreditsRequest) -> CreditWallet:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/credits/consume", json_body=dict(req), idempotent=True)
        )

    async def grant(self, req: GrantCreditsRequest) -> CreditWallet:
        return await self._c.request(
            RequestSpec("POST", "/api/v1/credits/grant", json_body=dict(req), idempotent=True)
        )


class RolesResource(_Base):
    async def list(self) -> List[Role]:
        return await self._c.request(RequestSpec("GET", "/api/v1/roles"))

    async def create(self, req: CreateRoleRequest) -> Role:
        return await self._c.request(RequestSpec("POST", "/api/v1/roles", json_body=dict(req), idempotent=True))

    async def update(self, role_id: str, req: UpdateRoleRequest) -> Role:
        return await self._c.request(
            RequestSpec("PATCH", f"/api/v1/roles/{role_id}", json_body=dict(req), idempotent=True)
        )

    async def assign(self, req: AssignRoleRequest) -> None:
        await self._c.request(RequestSpec("POST", "/api/v1/roles/assign", json_body=dict(req), idempotent=True))

    async def permissions(self) -> List[Permission]:
        return await self._c.request(RequestSpec("GET", "/api/v1/roles/permissions"))


class ProductsResource(_Base):
    async def list(self) -> List[Product]:
        return await self._c.request(RequestSpec("GET", "/api/v1/admin/products", as_platform_admin=True))

    async def create(self, req: CreateProductRequest) -> Product:
        return await self._c.request(
            RequestSpec(
                "POST",
                "/api/v1/admin/products",
                json_body=dict(req),
                as_platform_admin=True,
                idempotent=True,
            )
        )

    async def update(self, slug: str, req: UpdateProductRequest) -> Product:
        return await self._c.request(
            RequestSpec(
                "PATCH",
                f"/api/v1/admin/products/{slug}",
                json_body=dict(req),
                as_platform_admin=True,
                idempotent=True,
            )
        )
