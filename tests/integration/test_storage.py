"""HTTP coverage for the Storage API (`docs/architecture.md` § 6.3).

Mirrors the shape of test_jobs.py — happy path, optimistic concurrency,
cross-tenant + cross-product isolation, delete idempotency.
"""

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


async def _ensure_collection(
    client: AsyncClient, tok: dict, name: str = "prefs", product_slug: str = "producta"
) -> None:
    r = await client.post(
        "/api/v1/storage/collections",
        json={"name": name},
        headers=auth(tok["access_token"], product_slug),
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_collection_then_put_get(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok, "prefs")

    put = await client.put(
        "/api/v1/storage/prefs/theme",
        json={"value": {"mode": "dark"}},
        headers=auth(tok["access_token"]),
    )
    assert put.status_code == 200, put.text
    assert put.json()["version"] == 1
    assert put.json()["value"] == {"mode": "dark"}

    get = await client.get(
        "/api/v1/storage/prefs/theme", headers=auth(tok["access_token"])
    )
    assert get.status_code == 200
    body = get.json()
    assert body["key"] == "theme"
    assert body["value"] == {"mode": "dark"}
    assert body["version"] == 1


@pytest.mark.asyncio
async def test_put_bumps_version(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok)
    for expected in (1, 2, 3):
        r = await client.put(
            "/api/v1/storage/prefs/theme",
            json={"value": {"mode": f"v{expected}"}},
            headers=auth(tok["access_token"]),
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == expected


@pytest.mark.asyncio
async def test_optimistic_concurrency_conflict(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok)
    await client.put(
        "/api/v1/storage/prefs/theme",
        json={"value": {"v": 1}},
        headers=auth(tok["access_token"]),
    )
    # Wrong if_version → 409.
    bad = await client.put(
        "/api/v1/storage/prefs/theme",
        json={"value": {"v": 2}, "if_version": 99},
        headers=auth(tok["access_token"]),
    )
    assert bad.status_code == 409, bad.text
    assert bad.json()["code"] == "conflict"

    # Right if_version → 200, version=2.
    ok = await client.put(
        "/api/v1/storage/prefs/theme",
        json={"value": {"v": 2}, "if_version": 1},
        headers=auth(tok["access_token"]),
    )
    assert ok.status_code == 200
    assert ok.json()["version"] == 2


@pytest.mark.asyncio
async def test_get_unknown_key_is_404(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok)
    r = await client.get(
        "/api/v1/storage/prefs/missing", headers=auth(tok["access_token"])
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_put_to_unknown_collection_is_404(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.put(
        "/api/v1/storage/nope/x",
        json={"value": {}},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_documents_and_delta_sync(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok, "docs")

    await client.put(
        "/api/v1/storage/docs/a",
        json={"value": {"n": 1}},
        headers=auth(tok["access_token"]),
    )
    await client.put(
        "/api/v1/storage/docs/b",
        json={"value": {"n": 2}},
        headers=auth(tok["access_token"]),
    )

    r = await client.get(
        "/api/v1/storage/docs", headers=auth(tok["access_token"])
    )
    assert r.status_code == 200
    keys = [item["key"] for item in r.json()["items"]]
    assert set(keys) == {"a", "b"}

    # Delta-sync: ?since picks up writes after a watermark.
    mid_ts = r.json()["items"][-1]["updated_at"]
    # Wait a tick so a subsequent write has a strictly greater updated_at.
    await asyncio.sleep(0.05)
    await client.put(
        "/api/v1/storage/docs/c",
        json={"value": {"n": 3}},
        headers=auth(tok["access_token"]),
    )
    # Pass `since` via httpx's params= so it URL-encodes the `+` in the
    # ISO timezone offset for us.
    r = await client.get(
        "/api/v1/storage/docs",
        params={"since": mid_ts},
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 200, r.text
    keys = [item["key"] for item in r.json()["items"]]
    assert "c" in keys


@pytest.mark.asyncio
async def test_delete_then_get_is_404(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    await _ensure_collection(client, tok)
    await client.put(
        "/api/v1/storage/prefs/theme",
        json={"value": {"x": 1}},
        headers=auth(tok["access_token"]),
    )
    delete = await client.delete(
        "/api/v1/storage/prefs/theme", headers=auth(tok["access_token"])
    )
    assert delete.status_code == 204

    # Idempotent: a second delete is still 204.
    delete2 = await client.delete(
        "/api/v1/storage/prefs/theme", headers=auth(tok["access_token"])
    )
    assert delete2.status_code == 204

    # GET → 404.
    r = await client.get(
        "/api/v1/storage/prefs/theme", headers=auth(tok["access_token"])
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_collection_idempotent(client: AsyncClient) -> None:
    """POST /collections with an existing name returns the existing row."""
    tok = await register_tenant(client, slug="acme")
    first = await client.post(
        "/api/v1/storage/collections",
        json={"name": "prefs"},
        headers=auth(tok["access_token"]),
    )
    second = await client.post(
        "/api/v1/storage/collections",
        json={"name": "prefs"},
        headers=auth(tok["access_token"]),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_cross_tenant_isolation(client: AsyncClient) -> None:
    a = await register_tenant(client, slug="alpha")
    b = await register_tenant(client, slug="beta")
    await _ensure_collection(client, a, "shared")
    await client.put(
        "/api/v1/storage/shared/secret",
        json={"value": {"v": "alpha-only"}},
        headers=auth(a["access_token"]),
    )

    # Tenant B has no "shared" collection — 404 on the collection lookup.
    r = await client.get(
        "/api/v1/storage/shared/secret", headers=auth(b["access_token"])
    )
    assert r.status_code == 404

    # Even if tenant B registers a collection with the same name, the
    # data is independent.
    await _ensure_collection(client, b, "shared")
    r = await client.get(
        "/api/v1/storage/shared/secret", headers=auth(b["access_token"])
    )
    assert r.status_code == 404

    # And tenant B's list is empty.
    r = await client.get(
        "/api/v1/storage/shared", headers=auth(b["access_token"])
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_cross_product_isolation(client: AsyncClient) -> None:
    a = await register_tenant(client, slug="acme", product_slug="producta")
    b = await register_tenant(
        client,
        slug="acme",
        email="owner@acme-b.example.com",
        product_slug="productb",
    )
    await _ensure_collection(client, a, "prefs", product_slug="producta")
    await client.put(
        "/api/v1/storage/prefs/x",
        json={"value": {"in": "producta"}},
        headers=auth(a["access_token"], "producta"),
    )

    # productb's same-slug tenant has no collection.
    r = await client.get(
        "/api/v1/storage/prefs/x", headers=auth(b["access_token"], "productb")
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401(client: AsyncClient) -> None:
    r = await client.put(
        "/api/v1/storage/prefs/x",
        json={"value": {}},
        headers={"X-Product-Slug": "producta"},
    )
    assert r.status_code == 401
