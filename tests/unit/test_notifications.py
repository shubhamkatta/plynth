"""Email provider: templates render, `log` mode sends nothing, `ses` mode maps
failures to a typed error and never logs secret values."""

import pytest

from app.core.config import settings
from app.providers import notifications


def test_templates_render_and_tolerate_missing_keys() -> None:
    subject, body = notifications.render("mfa_otp", {"code": "123456", "expires_minutes": 5})
    assert "123456" in body and "5" in body and subject
    # Missing placeholder → empty string, not KeyError.
    _, body = notifications.render("invite", {"name": "Pat"})
    assert "Pat" in body


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
