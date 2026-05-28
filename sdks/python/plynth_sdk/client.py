from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from plynth_sdk._http import (
    API_PREFIX,
    HttpConfig,
    RequestSpec,
    build_headers,
    is_admin_path,
    parse_response,
)
from plynth_sdk.auth import MemoryStore, TokenStore
from plynth_sdk.errors import PlynthNetworkError
from plynth_sdk.resources import sync as resources
from plynth_sdk.types import Tokens


class PlynthClient:
    """Synchronous client. Use as a context manager to manage the HTTP pool."""

    def __init__(
        self,
        *,
        base_url: str,
        product_slug: str | None = None,
        admin_token: str | None = None,
        acting_tenant_slug: str | None = None,
        token_store: TokenStore | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token_store: TokenStore = token_store or MemoryStore()
        self._cfg = HttpConfig(
            base_url=base_url.rstrip("/"),
            token_store=self.token_store,
            product_slug=product_slug,
            admin_token=admin_token,
            acting_tenant_slug=acting_tenant_slug,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        )
        self._http = httpx.Client(
            base_url=self._cfg.base_url,
            timeout=self._cfg.timeout,
            transport=transport,
        )

        self.auth = resources.AuthResource(self)
        self.tenants = resources.TenantsResource(self)
        self.users = resources.UsersResource(self)
        self.plans = resources.PlansResource(self)
        self.subscription = resources.SubscriptionResource(self)
        self.credits = resources.CreditsResource(self)
        self.roles = resources.RolesResource(self)
        self.products = resources.ProductsResource(self)

    # --- context manager ------------------------------------------------

    def __enter__(self) -> PlynthClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- low-level request ----------------------------------------------

    def request(self, spec: RequestSpec) -> Any:
        return self._send(spec, retried=False)

    def _send(self, spec: RequestSpec, *, retried: bool) -> Any:
        headers = build_headers(self._cfg, spec)
        try:
            r = self._http.request(
                spec.method,
                spec.path,
                headers=headers,
                json=spec.json_body,
                params=spec.params,
            )
        except httpx.HTTPError as exc:
            raise PlynthNetworkError(str(exc), exc) from exc

        is_user_call = (
            not spec.skip_auth
            and not spec.as_platform_admin
            and not is_admin_path(spec.path)
        )
        if r.status_code == 401 and is_user_call and not retried:
            if self._refresh():
                return self._send(spec, retried=True)

        return parse_response(r)

    def _refresh(self) -> bool:
        current = self.token_store.get()
        if not current:
            return False
        try:
            r = self._http.post(
                f"{API_PREFIX}/auth/refresh",
                json={"refresh_token": current["refresh_token"]},
            )
        except httpx.HTTPError:
            self.token_store.clear()
            return False
        if r.status_code != 200:
            self.token_store.clear()
            return False
        try:
            next_tokens: Tokens = r.json()
        except ValueError:
            self.token_store.clear()
            return False
        self.token_store.set(next_tokens)
        return True
