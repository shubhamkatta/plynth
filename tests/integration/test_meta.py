"""Meta endpoints + error envelope shape."""

import pytest
from httpx import AsyncClient

from tests.conftest import product_headers


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready(client: AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_404_envelope(client: AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert "code" in body and "message" in body and "details" in body


@pytest.mark.asyncio
async def test_validation_envelope(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email"},
        headers=product_headers("producta"),
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_failed"
    assert "errors" in body["details"]
