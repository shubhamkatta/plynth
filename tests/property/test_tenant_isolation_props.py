"""Property-based tests for cross-product / cross-tenant isolation.

These ride on top of the existing httpx async `client` fixture and the
helpers in `tests.conftest`. We use Hypothesis to randomize the inputs
(slugs, emails, product order) so the invariants are exercised against a
broader input space than the hand-written integration tests.

Async integration with Hypothesis: `@given` does NOT compose cleanly with
`pytest-asyncio` (it expects sync test functions). The portable workaround
is to take `st.data()` as a normal parameter and draw inside the async
test body. This keeps test setup synchronous and HTTP traffic async,
without depending on `hypothesis.extra.asyncio` (not available on all
versions).

We use very small example counts (`max_examples=10`) because each example
boots tenants over the live ASGI client. Hypothesis still gives us
shrinking + reproducible failure cases for free.
"""

import string

import pytest
from httpx import AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import get_redis
from tests.conftest import TENANT_TABLES, auth, register_tenant


async def _reset_tenant_data() -> None:
    """Truncate tenant tables between Hypothesis examples.

    The `_clean_tenant_data` autouse fixture only runs once per *pytest
    test*, not once per Hypothesis example. Without this, examples 2…N
    inherit the rows from example 1 and hit unique-constraint conflicts
    (e.g. duplicate tenant slug or owner email). Mirrors the fixture's
    truncate + redis flush so each example starts from a clean slate.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(TENANT_TABLES)} RESTART IDENTITY CASCADE")
        )
    redis = get_redis()
    await redis.flushdb()
    await redis.aclose()


# Lower-case ASCII slugs (length-bounded) matching the API's
# `^[a-z0-9-]+$` pattern.
slug_strategy = st.text(
    alphabet=string.ascii_lowercase + string.digits,
    min_size=4,
    max_size=20,
).filter(lambda s: s[0].isalpha())  # avoid leading-digit edge cases

# Email local-part: lowercase letters + digits, no dots / dashes to avoid
# normalization surprises.
email_local = st.text(
    alphabet=string.ascii_lowercase + string.digits,
    min_size=4,
    max_size=20,
).filter(lambda s: s[0].isalpha())

# Common Hypothesis settings for the HTTP-driven tests: shrink-friendly,
# small example count (each example provisions DB rows), no deadline
# because httpx round-trips can spike.
HTTP_SETTINGS = settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)


@pytest.mark.asyncio
@given(data=st.data())
@HTTP_SETTINGS
async def test_tenant_from_product_a_is_invisible_from_product_b(
    client: AsyncClient, data: st.DataObject
) -> None:
    # Why this property? Cross-product reads must never leak. Whatever
    # slug we register in producta, listing /tenants in productb must
    # not surface it — the per-request product context filters at the
    # repository layer.
    await _reset_tenant_data()
    slug = data.draw(slug_strategy, label="tenant_slug")

    a_tok = await register_tenant(client, slug=slug, product_slug="producta")
    b_tok = await register_tenant(
        client,
        slug=f"{slug}-b",  # distinct slug avoids confusion in failure output
        email=f"owner-b@{slug}-b.example.com",
        product_slug="productb",
    )

    listed_b = await client.get(
        "/api/v1/tenants", headers=auth(b_tok["access_token"], "productb")
    )
    assert listed_b.status_code == 200
    slugs_b = {t["slug"] for t in listed_b.json()}
    assert slug not in slugs_b, (
        f"tenant slug {slug!r} from producta leaked into productb listing"
    )

    # Sanity: producta still sees itself.
    listed_a = await client.get(
        "/api/v1/tenants", headers=auth(a_tok["access_token"], "producta")
    )
    assert slug in {t["slug"] for t in listed_a.json()}


@pytest.mark.asyncio
@given(data=st.data())
@HTTP_SETTINGS
async def test_token_from_product_a_rejected_with_product_b_header(
    client: AsyncClient, data: st.DataObject
) -> None:
    # Why this property? The JWT `pid` claim is bound at issue time. If
    # the X-Product-Slug header disagrees with `pid`, the middleware must
    # 403 — no exception. Otherwise a stolen token could be re-scoped to
    # any product by simply changing the header.
    await _reset_tenant_data()
    slug = data.draw(slug_strategy, label="tenant_slug")

    a_tok = await register_tenant(client, slug=slug, product_slug="producta")

    r = await client.get(
        "/api/v1/auth/me",
        headers=auth(a_tok["access_token"], "productb"),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


@pytest.mark.asyncio
@given(data=st.data())
@HTTP_SETTINGS
async def test_sibling_tenants_users_are_isolated(
    client: AsyncClient, data: st.DataObject
) -> None:
    # Why this property? Two sibling tenants in the same product must not
    # see each other's users. The /users listing is dual-filtered on
    # (product_id, tenant_id), and any regression that drops the tenant
    # filter would surface here as a foreign email leaking in.
    await _reset_tenant_data()
    s1 = data.draw(slug_strategy, label="tenant_a_slug")
    s2 = data.draw(slug_strategy.filter(lambda x: x != s1), label="tenant_b_slug")

    tok_a = await register_tenant(client, slug=s1)
    tok_b = await register_tenant(client, slug=s2)

    users_a = await client.get("/api/v1/users", headers=auth(tok_a["access_token"]))
    users_b = await client.get("/api/v1/users", headers=auth(tok_b["access_token"]))
    assert users_a.status_code == 200
    assert users_b.status_code == 200

    a_emails = {u["email"] for u in users_a.json()}
    b_emails = {u["email"] for u in users_b.json()}

    # Each tenant sees only its own owner email.
    assert a_emails == {f"owner@{s1}.example.com"}
    assert b_emails == {f"owner@{s2}.example.com"}
    # Defensive: no overlap in user IDs either.
    a_ids = {u["id"] for u in users_a.json()}
    b_ids = {u["id"] for u in users_b.json()}
    assert a_ids.isdisjoint(b_ids)


@pytest.mark.asyncio
@given(data=st.data())
@HTTP_SETTINGS
async def test_reinvite_after_soft_delete_succeeds(
    client: AsyncClient, data: st.DataObject
) -> None:
    # Why this property? Regression guard for the prior bug where the
    # `users.email` UNIQUE constraint blocked re-invite of a soft-deleted
    # user. The partial unique index (`WHERE deleted_at IS NULL`) must
    # mean: delete → invite same email → new user_id, 201 response.
    await _reset_tenant_data()
    tenant_slug = data.draw(slug_strategy, label="tenant_slug")
    local = data.draw(email_local, label="email_local")
    email = f"{local}@{tenant_slug}.example.com"

    owner = await register_tenant(client, slug=tenant_slug)
    headers = auth(owner["access_token"])

    invite1 = await client.post(
        "/api/v1/users",
        json={"email": email, "role_codes": ["member"]},
        headers=headers,
    )
    assert invite1.status_code == 201, invite1.text
    first_id = invite1.json()["id"]

    deleted = await client.delete(f"/api/v1/users/{first_id}", headers=headers)
    assert deleted.status_code == 204

    invite2 = await client.post(
        "/api/v1/users",
        json={"email": email, "role_codes": ["member"]},
        headers=headers,
    )
    assert invite2.status_code == 201, invite2.text
    second_id = invite2.json()["id"]

    assert second_id != first_id, (
        "re-invite returned the same user_id — soft delete + re-invite is "
        "supposed to allocate a new row"
    )
