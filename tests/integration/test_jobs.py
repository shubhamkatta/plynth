"""HTTP coverage for the Jobs API (`docs/architecture.md` § 6.2).

What this covers:
- Happy path: create → list → fetch → cancel.
- Idempotency-Key dedupes a retry to the same job row.
- Status transitions: cancel(queued) → 200, cancel(cancelled) → 409.
- Cross-tenant isolation: tenant A can't see tenant B's jobs.
- Cross-product isolation: same slug in productb hides producta's jobs.

Tests use the tenant `register_tenant` helper from conftest, which gives
the new owner the `owner` role (effective `*:*`). RBAC is exercised by
the dependency layer regardless.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth, register_tenant


@pytest.mark.asyncio
async def test_create_job_returns_202_and_persists(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.post(
        "/api/v1/jobs",
        json={
            "type": "transcription.audio_to_text",
            "payload": {"url": "s3://x/y.wav", "duration_seconds": 12},
            "reference": "client-corr-1",
        },
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]
    assert body["poll_url"].endswith(job_id)

    # GET by id returns the full shape.
    r2 = await client.get(f"/api/v1/jobs/{job_id}", headers=auth(tok["access_token"]))
    assert r2.status_code == 200, r2.text
    detail = r2.json()
    assert detail["job_id"] == job_id
    assert detail["type"] == "transcription.audio_to_text"
    assert detail["status"] == "queued"
    assert detail["reference"] == "client-corr-1"
    assert detail["payload"]["duration_seconds"] == 12
    assert detail["progress"] == 0
    assert detail["result"] is None
    assert detail["error"] is None


@pytest.mark.asyncio
async def test_list_jobs_filters_by_status(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    for i in range(3):
        r = await client.post(
            "/api/v1/jobs",
            json={"type": "export.csv", "payload": {"i": i}},
            headers=auth(tok["access_token"]),
        )
        assert r.status_code == 202, r.text

    # Without filter: 3.
    r = await client.get("/api/v1/jobs", headers=auth(tok["access_token"]))
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3

    # status=queued: 3 still.
    r = await client.get(
        "/api/v1/jobs?status=queued", headers=auth(tok["access_token"])
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3

    # status=done: 0 (no worker has touched them).
    r = await client.get(
        "/api/v1/jobs?status=done", headers=auth(tok["access_token"])
    )
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_idempotency_key_dedupes_retry(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    body = {"type": "ml.classify", "payload": {"x": 1}}
    headers = {**auth(tok["access_token"]), "Idempotency-Key": "client-xyz"}

    first = await client.post("/api/v1/jobs", json=body, headers=headers)
    second = await client.post("/api/v1/jobs", json=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]

    # And the list only has 1.
    r = await client.get("/api/v1/jobs", headers=auth(tok["access_token"]))
    assert len(r.json()["items"]) == 1


@pytest.mark.asyncio
async def test_idempotency_key_distinct_when_omitted(client: AsyncClient) -> None:
    """Two identical bodies *without* Idempotency-Key create two rows —
    that's the contract; dedupe is the client's opt-in."""
    tok = await register_tenant(client, slug="acme")
    body = {"type": "ml.classify", "payload": {"x": 1}}
    a = await client.post("/api/v1/jobs", json=body, headers=auth(tok["access_token"]))
    b = await client.post("/api/v1/jobs", json=body, headers=auth(tok["access_token"]))
    assert a.json()["job_id"] != b.json()["job_id"]


@pytest.mark.asyncio
async def test_cancel_queued_then_cancel_again_conflicts(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    create = await client.post(
        "/api/v1/jobs",
        json={"type": "noop", "payload": {}},
        headers=auth(tok["access_token"]),
    )
    job_id = create.json()["job_id"]

    cancel = await client.post(
        f"/api/v1/jobs/{job_id}/cancel", headers=auth(tok["access_token"])
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"
    assert cancel.json()["completed_at"] is not None

    # Second cancel → 409 (terminal state).
    again = await client.post(
        f"/api/v1/jobs/{job_id}/cancel", headers=auth(tok["access_token"])
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "conflict"


@pytest.mark.asyncio
async def test_get_unknown_job_is_404(client: AsyncClient) -> None:
    tok = await register_tenant(client, slug="acme")
    r = await client.get(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000001",
        headers=auth(tok["access_token"]),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_isolation(client: AsyncClient) -> None:
    """Tenant A's job is invisible to tenant B (and vice versa)."""
    a = await register_tenant(client, slug="alpha")
    b = await register_tenant(client, slug="beta")

    create = await client.post(
        "/api/v1/jobs",
        json={"type": "noop", "payload": {}},
        headers=auth(a["access_token"]),
    )
    a_job_id = create.json()["job_id"]

    # Tenant B can't fetch it by id.
    r = await client.get(
        f"/api/v1/jobs/{a_job_id}", headers=auth(b["access_token"])
    )
    assert r.status_code == 404

    # And tenant B's list is empty.
    r = await client.get("/api/v1/jobs", headers=auth(b["access_token"]))
    assert r.status_code == 200
    assert r.json()["items"] == []

    # Tenant A's list still has it.
    r = await client.get("/api/v1/jobs", headers=auth(a["access_token"]))
    assert any(item["job_id"] == a_job_id for item in r.json()["items"])


@pytest.mark.asyncio
async def test_cross_product_isolation(client: AsyncClient) -> None:
    """Same tenant slug in productb is a totally separate row set."""
    a = await register_tenant(client, slug="acme", product_slug="producta")
    b = await register_tenant(
        client,
        slug="acme",
        email="owner@acme-b.example.com",
        product_slug="productb",
    )
    create = await client.post(
        "/api/v1/jobs",
        json={"type": "noop", "payload": {}},
        headers=auth(a["access_token"], "producta"),
    )
    a_job_id = create.json()["job_id"]

    # productb's same-slug tenant cannot see producta's job.
    r = await client.get(
        f"/api/v1/jobs/{a_job_id}", headers=auth(b["access_token"], "productb")
    )
    assert r.status_code == 404

    r = await client.get("/api/v1/jobs", headers=auth(b["access_token"], "productb"))
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/jobs",
        json={"type": "noop", "payload": {}},
        headers={"X-Product-Slug": "producta"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_idempotency_scoped_per_tenant(client: AsyncClient) -> None:
    """Same Idempotency-Key in two tenants creates two distinct jobs —
    keys are scoped per (product, tenant)."""
    a = await register_tenant(client, slug="alpha")
    b = await register_tenant(client, slug="beta")
    body = {"type": "noop", "payload": {}}
    ra = await client.post(
        "/api/v1/jobs", json=body,
        headers={**auth(a["access_token"]), "Idempotency-Key": "shared"},
    )
    rb = await client.post(
        "/api/v1/jobs", json=body,
        headers={**auth(b["access_token"]), "Idempotency-Key": "shared"},
    )
    assert ra.status_code == 202
    assert rb.status_code == 202
    assert ra.json()["job_id"] != rb.json()["job_id"]
