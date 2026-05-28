from __future__ import annotations

import re

import httpx
import pytest
import respx

from plynth_sdk import MemoryStore, PlynthApiError, PlynthClient


def _client(store: MemoryStore, **kw: object) -> PlynthClient:
    return PlynthClient(
        base_url="https://api.test",
        product_slug="chatbot",
        token_store=store,
        **kw,  # type: ignore[arg-type]
    )


def test_sends_bearer_and_product_slug(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/tenants").mock(return_value=httpx.Response(200, json=[]))
        with _client(store) as c:
            c.tenants.list()
    req = route.calls.last.request
    assert req.headers["x-product-slug"] == "chatbot"
    assert req.headers["authorization"] == "Bearer a1"


def test_admin_path_routes_through_admin_token() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/admin/products").mock(
            return_value=httpx.Response(200, json=[])
        )
        with PlynthClient(base_url="https://api.test", admin_token="admin-secret") as c:
            c.products.list()
    req = route.calls.last.request
    assert req.headers["x-platform-admin-token"] == "admin-secret"
    assert "authorization" not in req.headers


def test_idempotency_key_auto_generated(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.post("/api/v1/credits/consume").mock(
            return_value=httpx.Response(200, json={})
        )
        with _client(store) as c:
            c.credits.consume({"feature_key": "x", "amount": "1"})
    req = route.calls.last.request
    assert re.match(r"^[0-9a-f-]{36}$", req.headers["idempotency-key"], re.I)


def test_x_acting_tenant_slug_header(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/tenants").mock(return_value=httpx.Response(200, json=[]))
        with _client(store, acting_tenant_slug="child") as c:
            c.tenants.list()
    assert route.calls.last.request.headers["x-acting-tenant-slug"] == "child"


def test_refresh_once_on_401(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        me = mock.get("/api/v1/auth/me")
        me.side_effect = [
            httpx.Response(401),
            httpx.Response(200, json={"id": "u", "email": "x@x", "permissions": []}),
        ]
        mock.post("/api/v1/auth/refresh").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "a2",
                    "refresh_token": "r2",
                    "token_type": "bearer",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        )
        with _client(store) as c:
            me_resp = c.auth.me()
    assert me_resp["email"] == "x@x"
    assert store.get()["access_token"] == "a2"


def test_refresh_failure_clears_store_and_raises(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        mock.get("/api/v1/auth/me").mock(
            return_value=httpx.Response(401, json={"code": "unauthorized", "message": "x"})
        )
        mock.post("/api/v1/auth/refresh").mock(return_value=httpx.Response(401))
        with _client(store) as c, pytest.raises(PlynthApiError) as exc:
            c.auth.me()
    assert exc.value.status == 401
    assert store.get() is None


def test_error_envelope_parsed(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        mock.post("/api/v1/credits/consume").mock(
            return_value=httpx.Response(
                402,
                json={"code": "insufficient_credits", "message": "not enough", "details": {"need": 5}},
            )
        )
        with _client(store) as c, pytest.raises(PlynthApiError) as exc:
            c.credits.consume({"feature_key": "x", "amount": "1"})
    err = exc.value
    assert err.status == 402
    assert err.code == "insufficient_credits"
    assert err.details["need"] == 5
