from __future__ import annotations

import httpx
import pytest
import respx

from plynth_sdk import AsyncPlynthClient, MemoryStore, PlynthApiError


async def test_async_sends_bearer_and_product_slug(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.get("/api/v1/tenants").mock(return_value=httpx.Response(200, json=[]))
        async with AsyncPlynthClient(
            base_url="https://api.test", product_slug="chatbot", token_store=store
        ) as c:
            await c.tenants.list()
    req = route.calls.last.request
    assert req.headers["x-product-slug"] == "chatbot"
    assert req.headers["authorization"] == "Bearer a1"


async def test_async_refresh_once_on_401(tokens) -> None:
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
        async with AsyncPlynthClient(
            base_url="https://api.test", product_slug="chatbot", token_store=store
        ) as c:
            me_resp = await c.auth.me()
    assert me_resp["email"] == "x@x"
    assert store.get()["access_token"] == "a2"


async def test_async_error_envelope_parsed(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        mock.post("/api/v1/credits/consume").mock(
            return_value=httpx.Response(
                402,
                json={"code": "insufficient_credits", "message": "x", "details": {"need": 5}},
            )
        )
        async with AsyncPlynthClient(
            base_url="https://api.test", product_slug="chatbot", token_store=store
        ) as c:
            with pytest.raises(PlynthApiError) as exc:
                await c.credits.consume({"feature_key": "x", "amount": "1"})
    assert exc.value.code == "insufficient_credits"
