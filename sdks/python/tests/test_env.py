"""Tests for the env-vars vault + service tokens SDK surface."""

from __future__ import annotations

import re

import httpx
import pytest
import respx

from plynth_sdk import AsyncPlynthClient, MemoryStore, PlynthApiError, PlynthClient


def test_admin_env_set_sends_admin_token_and_idem_key() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.put("/api/v1/admin/products/mayva/env/STRIPE").mock(
            return_value=httpx.Response(200, json={
                "key": "STRIPE", "is_secret": True, "description": None,
                "last_rotated_at": "2026-01-01T00:00:00Z", "preview": "sk_l…cdef",
            })
        )
        with PlynthClient(base_url="https://api.test", admin_token="admin-secret") as c:
            c.admin_env.set("mayva", "STRIPE",
                            {"value": "sk_live_xxx", "is_secret": True})
    req = route.calls.last.request
    assert req.headers["x-platform-admin-token"] == "admin-secret"
    assert re.match(r"^[0-9a-f-]{36}$", req.headers["idempotency-key"], re.I)
    assert b'"is_secret": true' in req.content or b'"is_secret":true' in req.content


def test_env_fetch_sends_service_token_only() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/env").mock(
            return_value=httpx.Response(200, json={"GOOGLE_CLIENT_ID": "abc",
                                                    "STRIPE_LIVE_KEY": "sk_xxx"})
        )
        with PlynthClient(
            base_url="https://api.test",
            service_token="pst_deadbeefcafe1234567890abcdef0011",
            token_store=MemoryStore(),
        ) as c:
            env = c.env.fetch()
    assert env == {"GOOGLE_CLIENT_ID": "abc", "STRIPE_LIVE_KEY": "sk_xxx"}
    req = route.calls.last.request
    assert req.headers["x-service-token"] == "pst_deadbeefcafe1234567890abcdef0011"
    assert "authorization" not in req.headers
    assert "x-platform-admin-token" not in req.headers


def test_env_fetch_without_service_token_raises() -> None:
    with PlynthClient(base_url="https://api.test") as c, pytest.raises(PlynthApiError) as exc:
        c.env.fetch()
    assert exc.value.code == "no_service_token"


def test_admin_env_reveal_includes_query_params() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/admin/products/mayva/env/STRIPE").mock(
            return_value=httpx.Response(200, json={
                "key": "STRIPE", "value": "sk_live_plaintext", "is_secret": True,
                "description": None, "last_rotated_at": "2026-01-01T00:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            })
        )
        with PlynthClient(base_url="https://api.test", admin_token="a") as c:
            detail = c.admin_env.reveal("mayva", "STRIPE", "rotation")
    assert detail["value"] == "sk_live_plaintext"
    assert "reveal=True" in str(route.calls.last.request.url) or \
           "reveal=true" in str(route.calls.last.request.url)
    assert "reason=rotation" in str(route.calls.last.request.url)


def test_service_tokens_issue_returns_raw_token() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        mock.post("/api/v1/admin/products/mayva/service-tokens").mock(
            return_value=httpx.Response(201, json={
                "id": "deadbeef-cafe-1111-2222-333344445555",
                "name": "backend", "scopes": ["env:read"],
                "expires_at": None, "revoked_at": None,
                "last_used_at": None, "last_used_ip": None,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "token": "pst_deadbeefcafe1234567890abcdef0011",
            })
        )
        with PlynthClient(base_url="https://api.test", admin_token="a") as c:
            issued = c.service_tokens.issue("mayva", {"name": "backend"})
    assert issued["token"] == "pst_deadbeefcafe1234567890abcdef0011"
    assert issued["scopes"] == ["env:read"]


async def test_async_env_fetch() -> None:
    with respx.mock(base_url="https://api.test") as mock:
        mock.get("/api/v1/env").mock(
            return_value=httpx.Response(200, json={"K": "v"})
        )
        async with AsyncPlynthClient(
            base_url="https://api.test",
            service_token="pst_x",
        ) as c:
            env = await c.env.fetch()
    assert env == {"K": "v"}
