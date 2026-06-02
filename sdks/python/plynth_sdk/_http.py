"""Shared header-build / refresh logic for both sync and async clients."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from plynth_sdk.auth import TokenStore
from plynth_sdk.errors import PlynthApiError

API_PREFIX = "/api/v1"


def is_admin_path(path: str) -> bool:
    return path.startswith(f"{API_PREFIX}/admin/")


@dataclass
class HttpConfig:
    base_url: str
    token_store: TokenStore
    product_slug: str | None = None
    admin_token: str | None = None
    # Per-product service token (`pst_…`) for the product-runtime
    # `/env` path. When `RequestSpec.as_service_token=True` AND this
    # field is set, the SDK sends `X-Service-Token` and skips
    # Authorization / X-Platform-Admin-Token. Never expose to clients.
    service_token: str | None = None
    acting_tenant_slug: str | None = None
    timeout: httpx.Timeout = field(
        default_factory=lambda: httpx.Timeout(30.0, connect=10.0)
    )


@dataclass
class RequestSpec:
    method: str
    path: str
    json_body: Any | None = None
    params: dict[str, Any] | None = None
    product_slug: str | None = None
    acting_tenant_slug: str | None = None
    as_platform_admin: bool = False
    as_service_token: bool = False
    skip_auth: bool = False
    idempotent: bool = False
    idempotency_key: str | None = None


def build_headers(cfg: HttpConfig, spec: RequestSpec) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if spec.json_body is not None:
        headers["Content-Type"] = "application/json"

    want_admin = spec.as_platform_admin or is_admin_path(spec.path)
    want_service_token = spec.as_service_token

    if want_service_token:
        if not cfg.service_token:
            raise PlynthApiError(
                401,
                "no_service_token",
                "Service token not configured on client.",
            )
        headers["X-Service-Token"] = cfg.service_token
    elif want_admin:
        if not cfg.admin_token:
            raise PlynthApiError(
                401,
                "no_platform_admin_token",
                "Platform admin token not configured on client.",
            )
        headers["X-Platform-Admin-Token"] = cfg.admin_token
    elif not spec.skip_auth:
        tokens = cfg.token_store.get()
        if tokens:
            headers["Authorization"] = f"Bearer {tokens['access_token']}"
        elif cfg.admin_token and cfg.product_slug:
            # Admin god-mode: no user session + admin token configured.
            headers["X-Platform-Admin-Token"] = cfg.admin_token

    slug = spec.product_slug or cfg.product_slug
    if slug:
        headers["X-Product-Slug"] = slug

    acting = spec.acting_tenant_slug or cfg.acting_tenant_slug
    if acting and not want_admin:
        headers["X-Acting-Tenant-Slug"] = acting

    if spec.idempotent or spec.idempotency_key:
        headers["Idempotency-Key"] = spec.idempotency_key or str(uuid.uuid4())

    return headers


def parse_response(response: httpx.Response) -> Any:
    """Translate an httpx response into a parsed body or raise PlynthApiError."""
    from plynth_sdk.errors import parse_error_response

    if response.status_code == 204 or not response.content:
        if response.is_success:
            return None
        raise parse_error_response(response)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not response.is_success:
        if isinstance(body, dict):
            raise PlynthApiError(
                response.status_code,
                str(body.get("code") or "http_error"),
                str(body.get("message") or response.reason_phrase or ""),
                body.get("details") if isinstance(body.get("details"), dict) else None,
            )
        raise PlynthApiError(
            response.status_code, "http_error", response.reason_phrase or "", None
        )
    return body
