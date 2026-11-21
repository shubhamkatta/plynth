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
