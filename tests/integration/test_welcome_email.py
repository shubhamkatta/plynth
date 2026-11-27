"""Registration sends a welcome email, and can never fail because of one
(queue T-042).

`grep -rn "send_email" app/` returned exactly four call sites — password
reset, invite, email-OTP and payment reminders. There was no registration,
welcome or address-verification email anywhere, so signup never depended on
email and was **not broken**: this is a missing nicety, not a bug. The body
already existed (`providers/email_templates._welcome`, registered in
`TEMPLATES`); nothing ever called it.

The one thing that must not regress: `notifications.send_email` **raises**
`EmailDeliveryFailed`, and a welcome mail that propagated it would turn a
successful registration into a 502 — the caller would believe signup failed
when the account, its tenant and its trial all exist, and retrying would then
hit "user already exists". So the failure path is pinned, not just the happy
one.
"""

import pytest
from httpx import AsyncClient

from app.providers import notifications
from tests.conftest import product_headers

PW = "a-long-enough-password-1"


@pytest.fixture
def sent(monkeypatch) -> list[dict]:
    """Capture every send instead of handing it to the provider."""
    calls: list[dict] = []

    async def _fake(*, to: str, template: str, context: dict) -> None:
        calls.append({"to": to, "template": template, "context": context})

    monkeypatch.setattr(notifications, "send_email", _fake)
    return calls


def _payload(slug: str, email: str) -> dict:
    return {
        "tenant_name": slug.title(),
        "tenant_slug": slug,
        "email": email,
        "password": PW,
        "full_name": "New Owner",
    }


@pytest.mark.asyncio
async def test_registering_sends_a_welcome_email(
    client: AsyncClient, sent: list[dict]
) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json=_payload("welcomeco", "owner@welcomeco.example.com"),
        headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text

    welcomes = [c for c in sent if c["template"] == "welcome"]
    assert len(welcomes) == 1
    assert welcomes[0]["to"] == "owner@welcomeco.example.com"
    # The template needs a name, the product it is welcoming them to, and
    # somewhere to go next — a welcome with no link is a dead end.
    context = welcomes[0]["context"]
    assert context["name"] == "New Owner"
    assert context["product_name"]
    assert context["link"]


@pytest.mark.asyncio
async def test_a_b2c_signup_is_welcomed_too(
    client: AsyncClient, sent: list[dict]
) -> None:
    """`register_individual` routes through `register`, so the hook covers
    both shapes rather than only the B2B one."""
    r = await client.post(
        "/api/v1/auth/register-individual",
        json={
            "email": "solo@example.com",
            "password": PW,
            "full_name": "Solo Practitioner",
        },
        headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text
    assert [c for c in sent if c["template"] == "welcome"]


@pytest.mark.asyncio
async def test_a_delivery_failure_cannot_fail_the_registration(
    client: AsyncClient, monkeypatch
) -> None:
    """The account exists and the trial has started by the time mail is sent.
    A provider outage must not tell the caller that signup failed."""

    async def _boom(*, to: str, template: str, context: dict) -> None:
        raise notifications.EmailDeliveryFailed("ses is on fire")

    monkeypatch.setattr(notifications, "send_email", _boom)

    r = await client.post(
        "/api/v1/auth/register",
        json=_payload("stillreg", "owner@stillreg.example.com"),
        headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text
    assert r.json()["access_token"]

    # And the account genuinely works afterwards.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@stillreg.example.com", "password": PW},
        headers=product_headers("producta"),
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_a_suppressed_recipient_cannot_fail_the_registration(
    client: AsyncClient, monkeypatch
) -> None:
    """`EmailSuppressed` subclasses `EmailDeliveryFailed`, so one except covers
    both. An address on the suppression list after an earlier bounce is still
    not a reason to refuse someone an account."""

    async def _suppressed(*, to: str, template: str, context: dict) -> None:
        raise notifications.EmailSuppressed("recipient is suppressed")

    monkeypatch.setattr(notifications, "send_email", _suppressed)

    r = await client.post(
        "/api/v1/auth/register",
        json=_payload("supprco", "owner@supprco.example.com"),
        headers=product_headers("producta"),
    )
    assert r.status_code == 201, r.text
