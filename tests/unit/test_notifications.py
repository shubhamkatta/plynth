"""Email provider: templates render, `log` mode sends nothing, `ses` mode maps
failures to a typed error and never logs secret values."""

import pytest

from app.core.config import settings
from app.providers import notifications


def test_templates_render_and_tolerate_missing_keys() -> None:
    msg = notifications.render("mfa_otp", {"code": "123456", "expires_minutes": 5})
    assert "123456" in msg.text and "5" in msg.text and msg.subject
    assert "123456" in msg.html
    # Missing context keys → defaults, not KeyError. A half-rendered email
    # still beats a 500 on signup.
    msg = notifications.render("invite", {"name": "Pat"})
    assert "Pat" in msg.text and "Pat" in msg.html


@pytest.mark.asyncio
async def test_log_mode_does_not_call_ses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "log")
    called: list[int] = []
    monkeypatch.setattr(notifications, "_ses_send", lambda **_: called.append(1))
    await notifications.send_email(to="a@b.example.com", template="mfa_otp",
                                   context={"code": "1", "expires_minutes": 5})
    assert called == []


@pytest.mark.asyncio
async def test_ses_mode_sends_rendered_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "ses")
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")
    sent: list[dict] = []
    monkeypatch.setattr(notifications, "_ses_send", lambda **kw: sent.append(kw))
    await notifications.send_email(to="a@b.example.com", template="mfa_otp",
                                   context={"code": "654321", "expires_minutes": 5})
    assert sent[0]["to"] == "a@b.example.com" and "654321" in sent[0]["body"]
    # The HTML part must go too, or every email silently stays plain text.
    assert "654321" in sent[0]["html"]


@pytest.mark.asyncio
async def test_ses_failure_becomes_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "ses")
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")

    def boom(**_: str) -> None:
        raise RuntimeError("ses down")

    monkeypatch.setattr(notifications, "_ses_send", boom)
    with pytest.raises(notifications.EmailDeliveryFailed):
        await notifications.send_email(to="a@b.example.com", template="mfa_otp", context={})

    monkeypatch.setattr(settings, "email_from_address", "")
    with pytest.raises(notifications.EmailDeliveryFailed):
        await notifications.send_email(to="a@b.example.com", template="mfa_otp", context={})


# --- bounce / complaint handling (T-018) -------------------------------------
#
# SES account-level suppression is enabled for BOUNCE and COMPLAINT, so AWS
# owns the suppression list itself. What plynth has to get right is (a) routing
# sends through a configuration set so bounce/complaint events are observable
# at all, and (b) telling a permanent refusal apart from a transient outage so
# a known-bad address is not retried — retrying known-bad addresses is what
# damages sender reputation.


class _Rejected(Exception):
    """Stand-in for botocore's ClientError, which is only importable when the
    ses extra is installed."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.response = {"Error": {"Code": code, "Message": message}}


def test_suppression_is_detected_from_the_error_code() -> None:
    assert notifications._is_suppressed_recipient(_Rejected("AccountSuppressionListError"))
    assert notifications._is_suppressed_recipient(_Rejected("SuppressedDestination"))
    # SES also reports it as MessageRejected with the reason in the message.
    assert notifications._is_suppressed_recipient(
        _Rejected("MessageRejected", "Email address is on the suppression list")
    )


def test_ordinary_failures_are_not_mistaken_for_suppression() -> None:
    # A throttle or an outage must stay retryable.
    assert not notifications._is_suppressed_recipient(_Rejected("Throttling"))
    assert not notifications._is_suppressed_recipient(_Rejected("ServiceUnavailable"))
    assert not notifications._is_suppressed_recipient(RuntimeError("connection reset"))


@pytest.mark.asyncio
async def test_a_suppressed_recipient_raises_the_permanent_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_provider", "ses")
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")

    def _boom(**_):
        raise _Rejected("AccountSuppressionListError")

    monkeypatch.setattr(notifications, "_ses_send", _boom)

    with pytest.raises(notifications.EmailSuppressed):
        await notifications.send_email(
            to="bounced@example.com",
            template="mfa_otp",
            context={"code": "1", "expires_minutes": 5},
        )


@pytest.mark.asyncio
async def test_suppressed_still_satisfies_existing_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EmailSuppressed subclasses EmailDeliveryFailed on purpose, so nothing
    that already catches the general error starts leaking a new exception."""
    monkeypatch.setattr(settings, "email_provider", "ses")
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")

    def _boom(**_):
        raise _Rejected("MessageRejected", "address is on the suppression list")

    monkeypatch.setattr(notifications, "_ses_send", _boom)

    with pytest.raises(notifications.EmailDeliveryFailed):
        await notifications.send_email(
            to="bounced@example.com",
            template="mfa_otp",
            context={"code": "1", "expires_minutes": 5},
        )


def test_configuration_set_is_omitted_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming a configuration set that does not exist makes SES reject every
    send, so an unset value must mean "omit the parameter", never empty-string
    it. This is the failure mode that would take all email down at once."""
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")
    monkeypatch.setattr(settings, "ses_configuration_set", "")

    captured: dict = {}

    class _Client:
        def send_email(self, **kw):
            captured.update(kw)

    monkeypatch.setitem(
        __import__("sys").modules, "boto3", type("m", (), {"client": lambda *a, **k: _Client()})
    )
    notifications._ses_send(to="a@b.example.com", subject="s", body="b")
    assert "ConfigurationSetName" not in captured


def test_configuration_set_is_attached_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a set configured, every send must carry it — that is the only way
    bounce and complaint events reach a destination we can see."""
    monkeypatch.setattr(settings, "email_from_address", "noreply@example.com")
    monkeypatch.setattr(settings, "ses_configuration_set", "plynth-transactional")

    captured: dict = {}

    class _Client:
        def send_email(self, **kw):
            captured.update(kw)

    monkeypatch.setitem(
        __import__("sys").modules, "boto3", type("m", (), {"client": lambda *a, **k: _Client()})
    )
    notifications._ses_send(to="a@b.example.com", subject="s", body="b")
    assert captured["ConfigurationSetName"] == "plynth-transactional"


# --- HTML bodies -------------------------------------------------------------
#
# These emails are the product's first impression, so the rules that keep them
# readable in real mail clients are pinned here rather than left to review.


def test_every_template_renders_both_bodies() -> None:
    """A template that renders only text would silently ship as a plain email."""
    for name in notifications.TEMPLATES:
        msg = notifications.render(name, {})
        assert msg.subject, f"{name}: no subject"
        assert msg.text.strip(), f"{name}: no text part"
        assert msg.html.lstrip().startswith("<!doctype html>"), f"{name}: no html part"
        assert "{" not in msg.subject, f"{name}: unrendered placeholder in subject"


def test_html_carries_inline_styles_not_just_a_stylesheet() -> None:
    """Gmail strips <head><style>. Anything the email needs to look right has
    to be inline, so the <style> block is enhancement only."""
    msg = notifications.render("welcome", {"name": "Priya", "link": "https://x.example"})
    assert 'style="' in msg.html
    # The card background is load-bearing; it must not live only in the sheet.
    assert "#ffffff" in msg.html


def test_html_sets_its_own_preheader() -> None:
    """Left unset, clients scrape the first text they find for the inbox
    snippet — usually a bare URL."""
    msg = notifications.render("password_reset", {"link": "https://x.example", "expires_minutes": 30})
    assert "30 minutes" in msg.html
    assert "max-height:0" in msg.html  # the hidden preheader div


def test_context_values_are_escaped_into_the_html() -> None:
    """Display names and practice names are user-controlled. They are escaped
    because they came from a user, not trusted because they came from our DB."""
    msg = notifications.render(
        "onboarding_complete", {"practice_name": '<script>alert(1)</script>'}
    )
    assert "<script>" not in msg.html
    assert "&lt;script&gt;" in msg.html


def test_a_missing_name_does_not_leave_a_hole_in_the_greeting() -> None:
    msg = notifications.render("welcome", {})
    assert "Hi," in msg.text
    assert "Hi ," not in msg.text and "Hi there" not in msg.text


def test_links_are_real_hrefs_so_the_cta_works() -> None:
    msg = notifications.render("invite", {"link": "https://app.mayva.ai/accept-invite?token=abc"})
    assert 'href="https://app.mayva.ai/accept-invite?token=abc"' in msg.html
    assert "https://app.mayva.ai/accept-invite?token=abc" in msg.text


def test_dark_mode_panels_flip_with_their_text() -> None:
    """Caught by looking at a rendered email in a dark-mode browser.

    The dark-mode block flips `.mv-text` to near-white. Any panel holding
    `.mv-text` content must also carry `.mv-panel`, or its background stays
    light and the text becomes invisible — silently, and only for readers
    whose client honours prefers-color-scheme, which is most of them.
    """
    import re

    for name in notifications.TEMPLATES:
        html = notifications.render(name, {"code": "1", "link": "https://x.example"}).html
        for cell in re.findall(r"<td[^>]*>.*?</td>", html, re.S):
            holds_flipping_text = 'class="mv-text"' in cell or "mv-text" in cell
            looks_like_a_panel = f"background:{notifications.email_templates.SOFT}" in cell
            if looks_like_a_panel and holds_flipping_text:
                assert "mv-panel" in cell, (
                    f"{name}: a panel holding mv-text content is missing mv-panel, "
                    "so dark mode will render light text on a light panel"
                )
