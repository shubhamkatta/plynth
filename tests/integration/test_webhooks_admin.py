"""Integration coverage for the outbound (admin-managed) webhook routes.

These exercise the surface mounted at:

    /api/v1/admin/products/{slug}/webhooks

The router is included in `app.api.v1.router.api_router` by the parent
integration commit; this test module also defensively mounts it on the
shared `app` if it's not present yet, so the suite passes during the
seam where the feature has landed but the router wiring hasn't.

Coverage:
- Create returns the secret exactly once; list / get hide it.
- PATCH events filter + DELETE soft-deactivates.
- POST /{id}/test creates a delivery row.
- Cross-product isolation (endpoints in productb invisible to producta).
- Non-https URL is rejected at validation.
"""

import pytest
from httpx import AsyncClient

from app.api.v1 import webhooks_admin
from app.api.v1.router import api_router
from tests.conftest import platform_admin_headers


def _ensure_mounted() -> None:
    """Mount the webhooks_admin router on api_router if the parent
    integration commit hasn't done so yet. Idempotent."""
    mount = "/admin/products/{slug}/webhooks"
    already = any(
        getattr(r, "path", "").startswith(mount) for r in api_router.routes
    )
    if not already:
        api_router.include_router(
            webhooks_admin.router, prefix=mount, tags=["webhooks"],
        )


_ensure_mounted()


def _base(slug: str = "producta") -> str:
    return f"/api/v1/admin/products/{slug}/webhooks"


# --- create ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_endpoint_returns_secret_once(client: AsyncClient) -> None:
    r = await client.post(
        _base(),
        json={
            "url": "https://example.com/hook",
            "description": "my hook",
            "events": ["subscription.*", "tenant.deleted"],
        },
        headers=platform_admin_headers(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["subscription.*", "tenant.deleted"]
    assert body["is_active"] is True
    # Secret is present on create response, and looks non-trivial.
    assert "secret" in body and len(body["secret"]) >= 30
    endpoint_id = body["id"]

    # GET-by-id never returns the secret.
    show = await client.get(f"{_base()}/{endpoint_id}", headers=platform_admin_headers())
    assert show.status_code == 200, show.text
    assert "secret" not in show.json()

    # LIST never returns the secret either.
    listed = await client.get(_base(), headers=platform_admin_headers())
    assert listed.status_code == 200, listed.text
    assert all("secret" not in item for item in listed.json())


@pytest.mark.asyncio
async def test_create_rejects_non_https_url(client: AsyncClient) -> None:
    r = await client.post(
        _base(),
        json={"url": "http://insecure.example.com/hook"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_requires_admin_token(client: AsyncClient) -> None:
    r = await client.post(_base(), json={"url": "https://example.com/hook"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_unknown_product_404s(client: AsyncClient) -> None:
    r = await client.post(
        _base("does-not-exist"),
        json={"url": "https://example.com/hook"},
        headers=platform_admin_headers(),
    )
    assert r.status_code == 404


# --- isolation -------------------------------------------------------------

@pytest.mark.asyncio
async def test_endpoints_scoped_per_product(client: AsyncClient) -> None:
    """Registering an endpoint in productb must not appear under producta."""
    rb = await client.post(
        _base("productb"),
        json={"url": "https://b.example.com/hook"},
        headers=platform_admin_headers(),
    )
    assert rb.status_code == 201, rb.text
    b_id = rb.json()["id"]

    listed_a = await client.get(_base("producta"), headers=platform_admin_headers())
    a_ids = {item["id"] for item in listed_a.json()}
    assert b_id not in a_ids

    # And cross-product GET-by-id is 404 (not 200 with leak).
    leak = await client.get(f"{_base('producta')}/{b_id}", headers=platform_admin_headers())
    assert leak.status_code == 404


# --- update / delete -------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_updates_events_filter(client: AsyncClient) -> None:
    create = await client.post(
        _base(),
        json={"url": "https://example.com/hook", "events": ["a.*"]},
        headers=platform_admin_headers(),
    )
    endpoint_id = create.json()["id"]

    patch = await client.patch(
        f"{_base()}/{endpoint_id}",
        json={"events": ["b.*", "c.created"], "description": "updated"},
        headers=platform_admin_headers(),
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["events"] == ["b.*", "c.created"]
    assert patch.json()["description"] == "updated"


@pytest.mark.asyncio
async def test_patch_rejects_non_https_url(client: AsyncClient) -> None:
    create = await client.post(
        _base(),
        json={"url": "https://example.com/hook"},
        headers=platform_admin_headers(),
    )
    endpoint_id = create.json()["id"]

    bad = await client.patch(
        f"{_base()}/{endpoint_id}",
        json={"url": "ftp://example.com/hook"},
        headers=platform_admin_headers(),
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_delete_soft_deactivates(client: AsyncClient) -> None:
    create = await client.post(
        _base(),
        json={"url": "https://example.com/hook"},
        headers=platform_admin_headers(),
    )
    endpoint_id = create.json()["id"]

    deleted = await client.delete(
        f"{_base()}/{endpoint_id}", headers=platform_admin_headers(),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["is_active"] is False

    # Still visible (soft delete preserves history).
    show = await client.get(
        f"{_base()}/{endpoint_id}", headers=platform_admin_headers(),
    )
    assert show.status_code == 200
    assert show.json()["is_active"] is False


# --- test dispatch ---------------------------------------------------------

@pytest.mark.asyncio
async def test_test_endpoint_creates_pending_delivery(client: AsyncClient) -> None:
    create = await client.post(
        _base(),
        json={"url": "https://example.com/hook"},
        headers=platform_admin_headers(),
    )
    endpoint_id = create.json()["id"]

    fire = await client.post(
        f"{_base()}/{endpoint_id}/test",
        headers=platform_admin_headers(),
    )
    assert fire.status_code == 201, fire.text
    delivery = fire.json()
    assert delivery["status"] == "pending"
    assert delivery["event_type"] == "webhook.test"
    assert delivery["endpoint_id"] == endpoint_id
    assert delivery["payload"]["event"] == "webhook.test"

    # And the deliveries listing should now contain it.
    listed = await client.get(
        f"{_base()}/{endpoint_id}/deliveries",
        headers=platform_admin_headers(),
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert any(d["id"] == delivery["id"] for d in rows)


@pytest.mark.asyncio
async def test_test_endpoint_unknown_endpoint_404s(client: AsyncClient) -> None:
    bogus = "00000000-0000-0000-0000-000000000000"
    r = await client.post(
        f"{_base()}/{bogus}/test", headers=platform_admin_headers(),
    )
    assert r.status_code == 404


# --- signing helper --------------------------------------------------------

def test_sign_payload_is_deterministic_and_verifiable() -> None:
    """Unit-style: HMAC over '{ts}.{body}' with the secret, hex-encoded.
    Subscribers re-derive the same value to authenticate."""
    import hashlib
    import hmac

    from app.services.webhook_endpoint import sign_payload

    secret = "supersecret"
    body = '{"a":1}'
    ts = 1700000000
    header = sign_payload(secret=secret, body=body, timestamp=ts)
    assert header.startswith(f"t={ts},v1=")
    expected = hmac.new(
        secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    assert header == f"t={ts},v1={expected}"
