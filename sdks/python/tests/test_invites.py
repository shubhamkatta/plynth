"""Invite endpoints on the SDK (T-025).

The four invite endpoints existed on the platform but had no SDK methods, which
breaks the repo's contract that new endpoints ship with SDK coverage. These
tests pin the parts that are easy to get wrong across two auth surfaces:

- preview/accept are UNAUTHENTICATED — the token in the body is the credential,
  so no Bearer header should be required to call them.
- the prospect invite is PLATFORM-ADMIN, not a user JWT, so it must route
  through the admin-token header, not Authorization.
- a tenant invite and a prospect invite are different endpoints with different
  blast radius: one adds a teammate to your tenant, the other creates a whole
  new tenant. Hitting the wrong one is a tenancy bug, so the paths are asserted
  explicitly.
"""

from __future__ import annotations

import json

import httpx
import respx

from plynth_sdk import MemoryStore, PlynthClient

INVITE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "email": "new@example.test",
    "kind": "tenant",
    "expires_at": "2099-01-01T00:00:00Z",
    "link": None,
}


def _client(store: MemoryStore) -> PlynthClient:
    return PlynthClient(
        base_url="https://api.test", product_slug="chatbot", token_store=store
    )


def test_tenant_invite_posts_to_users_invites(tokens) -> None:
    store = MemoryStore()
    store.set(tokens)
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.post("/api/v1/users/invites").mock(
            return_value=httpx.Response(201, json=INVITE)
        )
        with _client(store) as c:
            out = c.users.create_invite(
                {"email": "new@example.test", "role_codes": ["therapist"]}
            )

    assert out["email"] == "new@example.test"
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"email": "new@example.test", "role_codes": ["therapist"]}
    # Tenant invites are a user action, so they carry the user's Bearer token.
    assert route.calls.last.request.headers["authorization"] == "Bearer a1"


def test_prospect_invite_uses_the_admin_token_not_a_bearer() -> None:
    """A prospect invite creates a NEW tenant — platform-admin only. If this
    ever went out over a user JWT it would be a privilege escalation."""
    prospect = {**INVITE, "kind": "prospect", "link": "https://api.test/invite?token=t"}
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.post("/api/v1/admin/products/mayva-practice/invites").mock(
            return_value=httpx.Response(201, json=prospect)
        )
        with PlynthClient(base_url="https://api.test", admin_token="admin-secret") as c:
            out = c.products.create_invite(
                "mayva-practice",
                {"email": "prospect@example.test", "send_email": False},
            )

    assert out["link"] == "https://api.test/invite?token=t"
    req = route.calls.last.request
    assert req.headers["x-platform-admin-token"] == "admin-secret"
    assert "authorization" not in req.headers
    # send_email:False is how invites go out while SES is sandboxed — it must
    # survive serialization, not get dropped as a falsy value.
    assert json.loads(req.content)["send_email"] is False


def test_preview_needs_no_authentication() -> None:
    """The invite token in the body IS the credential — an invitee has no
    account yet, so requiring a Bearer here would make preview uncallable."""
    preview = {
        "email": "new@example.test",
        "full_name": None,
        "kind": "prospect",
        "plan_code": "practice",
        "product_name": "Mayva",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.post("/api/v1/auth/invites/preview").mock(
            return_value=httpx.Response(200, json=preview)
        )
        with PlynthClient(base_url="https://api.test", product_slug="chatbot") as c:
            out = c.auth.preview_invite({"token": "t" * 24})

    assert out["product_name"] == "Mayva"
    assert "authorization" not in route.calls.last.request.headers


def test_accept_returns_a_token_pair_so_there_is_no_second_login() -> None:
    pair = {
        "access_token": "new-a",
        "refresh_token": "new-r",
        "token_type": "bearer",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    with respx.mock(base_url="https://api.test") as mock:
        route = mock.post("/api/v1/auth/invites/accept").mock(
            return_value=httpx.Response(201, json=pair)
        )
        with PlynthClient(base_url="https://api.test", product_slug="chatbot") as c:
            out = c.auth.accept_invite(
                {"token": "t" * 24, "password": "hunter2hunter2", "full_name": "Pat"}
            )

    assert out["access_token"] == "new-a"
    assert "authorization" not in route.calls.last.request.headers
    # Idempotent: a double-submitted accept form must not create two accounts.
    assert "idempotency-key" in route.calls.last.request.headers
