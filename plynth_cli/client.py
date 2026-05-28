"""HTTP client for the Plynth REST API — thin shim over `plynth_sdk.PlynthClient`.

The CLI predates the public SDK; this module is now a back-compat surface
that preserves the original ``ApiClient.get/post/patch/delete`` interface
so every command under ``plynth_cli.commands.*`` keeps working unchanged.

What's different vs the pre-SDK version:

* Header building, refresh-once-on-401, error envelope parsing, and
  idempotency-key generation all live in ``plynth_sdk`` now.
* Token storage is delegated via a small adapter (``_CliTokenStore``)
  that reads and writes the existing ``cfg["session"]`` dict so the
  on-disk config layout is unchanged.
* ``ApiCallError`` is now an alias for ``plynth_sdk.PlynthApiError`` —
  existing ``except ApiCallError`` clauses continue to catch SDK
  exceptions.
* Transport errors are mapped to ``ApiCallError(0, "network_error", …)``
  for back-compat (the SDK natively raises ``PlynthNetworkError``).
"""

from __future__ import annotations

from typing import Any

from plynth_sdk import PlynthApiError, PlynthClient, PlynthNetworkError
from plynth_sdk._http import RequestSpec
from plynth_sdk.types import Tokens

from plynth_cli import config as cfg_mod

API_PREFIX = "/api/v1"


# Back-compat alias. PlynthApiError has the same (status, code, message, details)
# constructor shape, so existing call sites that *construct* ApiCallError still
# work, and existing `except ApiCallError` blocks catch SDK exceptions.
ApiCallError = PlynthApiError


class _CliTokenStore:
    """Adapter: reads/writes the access/refresh pair from ``cfg["session"]``.

    The CLI's on-disk session dict carries ``product_slug`` and ``email``
    alongside the tokens (see ``plynth_cli/config.py``). We only touch
    the token fields here; the rest of the dict is preserved across
    refreshes so ``plynth whoami`` keeps showing the right product/email.
    """

    def get(self) -> Tokens | None:
        cfg = cfg_mod.load_config()
        s = cfg.get("session")
        if not s or not s.get("access_token"):
            return None
        return {
            "access_token": s["access_token"],
            "refresh_token": s.get("refresh_token", ""),
            "token_type": "bearer",
            "expires_at": s.get("expires_at") or "",
        }

    def set(self, tokens: Tokens) -> None:
        cfg = cfg_mod.load_config()
        s = dict(cfg.get("session") or {})
        s["access_token"] = tokens["access_token"]
        s["refresh_token"] = tokens["refresh_token"]
        s["expires_at"] = tokens.get("expires_at")
        cfg["session"] = s
        cfg_mod.save_config(cfg)

    def clear(self) -> None:
        cfg_mod.clear_session()


class ApiClient:
    """One-shot client. Reload after a config change.

    Preserves the original ``get/post/patch/delete`` surface. Reloads
    config from disk on construction; create a fresh ``ApiClient`` after
    you mutate the on-disk config (e.g. after ``plynth login``).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        product_slug: str | None = None,
        acting_tenant_slug: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._cfg = cfg_mod.load_config()
        self.base_url = (
            base_url or self._cfg.get("base_url") or cfg_mod.DEFAULT_BASE_URL
        ).rstrip("/")
        self._product_override = product_slug
        self._acting_tenant_override = acting_tenant_slug

        # Default product slug resolution: explicit override → session
        # product → admin-default product. Per-call overrides go through
        # RequestSpec.product_slug at request time and trump this.
        session = self._cfg.get("session") or {}
        default_slug = (
            product_slug
            or session.get("product_slug")
            or self._cfg.get("admin_product_slug")
        )

        self._sdk = PlynthClient(
            base_url=self.base_url,
            product_slug=default_slug,
            admin_token=self._cfg.get("admin_token"),
            acting_tenant_slug=acting_tenant_slug or self._cfg.get("acting_tenant_slug"),
            token_store=_CliTokenStore(),
            timeout=timeout,
        )

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
    ) -> Any:
        """Make an authenticated request and parse the JSON response.

        On HTTP errors raises ``ApiCallError`` with the platform's envelope.
        On transport failures raises ``ApiCallError(0, "network_error", …)``.
        On 204 / empty body returns ``None``.
        """
        spec = RequestSpec(
            method=method,
            path=path,
            json_body=json_body,
            params=params,
            skip_auth=skip_auth,
            as_platform_admin=as_platform_admin,
            product_slug=product_slug,
            acting_tenant_slug=acting_tenant_slug,
            idempotent=idempotent,
            idempotency_key=idempotency_key,
        )
        try:
            return self._sdk.request(spec)
        except PlynthNetworkError as exc:
            raise ApiCallError(0, "network_error", str(exc)) from exc

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
