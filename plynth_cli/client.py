"""HTTP client for the Plynth REST API.

Mirrors the behaviour of ``apps/admin-electron/src/main/api/client.ts``:

* Resolves auth in order:  explicit ``as_platform_admin`` / admin-only path
  → platform-admin token; user session → ``Bearer`` JWT;
  no session but admin token configured → admin god-mode.
* Sets ``X-Product-Slug`` from explicit arg → session product → admin
  default product.
* Sets ``X-Acting-Tenant-Slug`` when configured.
* Generates ``Idempotency-Key`` when ``idempotent=True``.
* On 401 (user JWT only), refreshes once and retries the original call.
* Parses the platform's ApiError envelope ``{code, message, details}``
  and raises ``ApiCallError``.

Library deps: ``httpx`` only (already a production dep of the platform).
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from plynth_cli import config as cfg_mod

API_PREFIX = "/api/v1"
_PLATFORM_ADMIN_PATH_PREFIXES = (f"{API_PREFIX}/admin/",)
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class ApiCallError(Exception):
    """Raised for any non-2xx response. Carries the API error envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _is_platform_admin_path(path: str) -> bool:
    return any(path.startswith(p) for p in _PLATFORM_ADMIN_PATH_PREFIXES)


class ApiClient:
    """One-shot client. Reload after a config change."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        product_slug: str | None = None,
        acting_tenant_slug: str | None = None,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    ) -> None:
        self._cfg = cfg_mod.load_config()
        self.base_url = (base_url or self._cfg.get("base_url") or cfg_mod.DEFAULT_BASE_URL).rstrip("/")
        # Per-call override > session product > admin default product.
        self._product_override = product_slug
        self._acting_tenant_override = acting_tenant_slug
        self._timeout = timeout

    # ---- introspection helpers (used by `whoami`) -----------------------

    @property
    def session(self) -> dict[str, Any] | None:
        return self._cfg.get("session")

    @property
    def admin_token(self) -> str | None:
        return self._cfg.get("admin_token")

    @property
    def admin_product_slug(self) -> str | None:
        return self._cfg.get("admin_product_slug")

    @property
    def acting_tenant_slug(self) -> str | None:
        return self._acting_tenant_override or self._cfg.get("acting_tenant_slug")

    # ---- header builder -------------------------------------------------

    def _resolve_product_slug(self, want_admin: bool, override: str | None) -> str | None:
        session = self.session
        return (
            override
            or self._product_override
            or (session.get("product_slug") if session else None)
            or (self.admin_product_slug if (want_admin or not session) else None)
        )

    def _build_headers(
        self,
        path: str,
        *,
        skip_auth: bool,
        as_platform_admin: bool,
        product_slug: str | None,
        acting_tenant_slug: str | None,
        idempotent: bool,
        idempotency_key: str | None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        want_admin = as_platform_admin or _is_platform_admin_path(path)
        session = None if skip_auth else self.session
        admin_token = self.admin_token
        admin_god_mode = (not want_admin) and (not session) and bool(admin_token) and bool(self.admin_product_slug)

        if want_admin:
            if not admin_token:
                raise ApiCallError(
                    401,
                    "no_platform_admin_token",
                    "platform admin token not configured. Run `plynth login --admin-token <TOKEN>`.",
                )
            headers["X-Platform-Admin-Token"] = admin_token
        elif session:
            headers["Authorization"] = f"Bearer {session['access_token']}"
        elif admin_god_mode:
            headers["X-Platform-Admin-Token"] = admin_token  # type: ignore[assignment]

        slug = self._resolve_product_slug(want_admin, product_slug)
        if slug and not want_admin:
            headers["X-Product-Slug"] = slug
        elif slug and want_admin and (product_slug or self._product_override):
            # Some admin endpoints accept both (e.g. seeding plans).
            headers["X-Product-Slug"] = slug

        acting = acting_tenant_slug or self.acting_tenant_slug
        if acting and not want_admin:
            headers["X-Acting-Tenant-Slug"] = acting

        if idempotent or idempotency_key:
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())

        return headers

    # ---- refresh-once -----------------------------------------------------

    def _refresh(self) -> bool:
        session = self.session
        if not session or not session.get("refresh_token"):
            return False
        url = f"{self.base_url}{API_PREFIX}/auth/refresh"
        try:
            r = httpx.post(
                url,
                json={"refresh_token": session["refresh_token"]},
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            cfg_mod.clear_session()
            return False
        if r.status_code != 200:
            cfg_mod.clear_session()
            return False
        body = r.json()
        new_session = dict(session)
        new_session.update({
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_at": body["expires_at"],
        })
        cfg = cfg_mod.load_config()
        cfg["session"] = new_session
        cfg_mod.save_config(cfg)
        self._cfg = cfg
        return True

    # ---- request --------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
        skip_auth: bool = False,
        as_platform_admin: bool = False,
        product_slug: str | None = None,
        acting_tenant_slug: str | None = None,
        idempotent: bool = False,
        idempotency_key: str | None = None,
        _retried: bool = False,
    ) -> Any:
        """Make an authenticated request and parse the JSON response.

        On HTTP errors raises ``ApiCallError`` with the platform's envelope.
        On 204 / empty body returns ``None``.
        """
        url = f"{self.base_url}{path}"
        headers = self._build_headers(
            path,
            skip_auth=skip_auth,
            as_platform_admin=as_platform_admin,
            product_slug=product_slug,
            acting_tenant_slug=acting_tenant_slug,
            idempotent=idempotent,
            idempotency_key=idempotency_key,
        )

        try:
            r = httpx.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ApiCallError(0, "network_error", str(exc)) from exc

        # 401 on a user-JWT call → refresh once, retry the original.
        if (
            r.status_code == 401
            and not skip_auth
            and not as_platform_admin
            and not _is_platform_admin_path(path)
            and not _retried
            and self.session is not None
        ):
            if self._refresh():
                return self.request(
                    method,
                    path,
                    json_body=json_body,
                    params=params,
                    skip_auth=skip_auth,
                    as_platform_admin=as_platform_admin,
                    product_slug=product_slug,
                    acting_tenant_slug=acting_tenant_slug,
                    idempotent=idempotent,
                    idempotency_key=idempotency_key,
                    _retried=True,
                )

        if r.status_code == 204 or not r.content:
            if r.is_success:
                return None
            raise ApiCallError(r.status_code, "http_error", r.reason_phrase or "")

        try:
            body = r.json()
        except ValueError:
            body = {"code": "parse_error", "message": r.text[:500], "details": {}}

        if not r.is_success:
            if isinstance(body, dict):
                raise ApiCallError(
                    r.status_code,
                    str(body.get("code") or "http_error"),
                    str(body.get("message") or r.reason_phrase or ""),
                    body.get("details") if isinstance(body.get("details"), dict) else None,
                )
            raise ApiCallError(r.status_code, "http_error", r.reason_phrase or "")

        return body

    # convenience verbs --------------------------------------------------

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, json_body: Any = None, **kw: Any) -> Any:
        return self.request("POST", path, json_body=json_body, **kw)

    def patch(self, path: str, json_body: Any = None, **kw: Any) -> Any:
        return self.request("PATCH", path, json_body=json_body, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)


def get_client(ctx_obj: dict[str, Any]) -> ApiClient:
    """Build an ApiClient from Click context globals."""
    return ApiClient(
        base_url=ctx_obj.get("base_url"),
        product_slug=ctx_obj.get("product_slug"),
        acting_tenant_slug=ctx_obj.get("acting_tenant_slug"),
    )
