"""Notification provider.

`EMAIL_PROVIDER=log` (default) only logs — safe for dev/test. `ses` sends via
Amazon SES (boto3, run in a worker thread so the event loop never blocks).

Never log secret values (OTP codes, invite/reset tokens, links). Logs carry
the template name and the context KEYS only.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class EmailDeliveryFailed(AppError):
    status_code = 502
    code = "email_delivery_failed"


class EmailSuppressed(EmailDeliveryFailed):
    """The recipient is on SES's suppression list — a PERMANENT refusal.

    SES account-level suppression is enabled for BOUNCE and COMPLAINT, so AWS
    maintains this list itself: a hard bounce or a spam complaint adds the
    address automatically and later sends to it are refused. That is the
    bounce/complaint *handling*; we do not keep a second list of our own,
    because a duplicate would drift from the authoritative one.

    It subclasses EmailDeliveryFailed so existing callers keep working, but is
    raised separately so retry logic can tell "this will never work" from
    "try again later". Retrying a suppressed address does not just waste a
    call — repeatedly sending to known-bad addresses is what damages a
    sender reputation in the first place.
    """

# template -> (subject, plain-text body). `{placeholders}` come from `context`.
TEMPLATES: dict[str, tuple[str, str]] = {
    "invite": (
        "You're invited to {product_name}",
        "Hi {name},\n\n{inviter} invited you to {product_name}.\n\n"
        "Accept your invite and set a password here (valid for {expires_days} days):\n"
        "{link}\n\nIf you weren't expecting this, you can ignore this email.\n",
    ),
    "password_reset": (
        "Reset your password",
        "Use this link to reset your password (valid for {expires_minutes} minutes):\n"
        "{link}\n\nIf you didn't request this, ignore this email.\n",
    ),
    "mfa_otp": (
        "Your verification code",
        "Your verification code is {code}. It expires in {expires_minutes} minutes.\n",
    ),
    "payment_reminder": (
        "Payment reminder for {tenant}",
        "Your payment of {amount_cents} {currency} is due {due_at}.\n{hosted_url}\n",
    ),
}


class _SafeDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def render(template: str, context: dict[str, Any]) -> tuple[str, str]:
    """Return (subject, body). Unknown templates raise KeyError (programmer error)."""
    subject, body = TEMPLATES[template]
    ctx = _SafeDict(context)
    return subject.format_map(ctx), body.format_map(ctx)


def _ses_send(*, to: str, subject: str, body: str) -> None:
    import boto3  # type: ignore[import-untyped]  # lazy: only needed when EMAIL_PROVIDER=ses

    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    client = boto3.client("sesv2", **kwargs)
    params: dict[str, Any] = {
        "FromEmailAddress": settings.email_from_address,
        "Destination": {"ToAddresses": [to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            }
        },
    }
    # Only when configured: naming a non-existent configuration set makes SES
    # reject the send outright, so an unset value must mean "omit", not "".
    if settings.ses_configuration_set:
        params["ConfigurationSetName"] = settings.ses_configuration_set
    client.send_email(**params)


def _is_suppressed_recipient(exc: BaseException) -> bool:
    """True when SES refused because the address is on the suppression list.

    Matched on the botocore error code rather than the message, and without
    importing botocore (it is only present when EMAIL_PROVIDER=ses). SES
    reports a suppressed destination as ``MessageRejected`` with the reason in
    the message, and ``AccountSuppressionListError`` where it has a code of
    its own.
    """
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
    if code in {"AccountSuppressionListError", "SuppressedDestination"}:
        return True
    text = f"{code} {exc}".lower()
    return "suppress" in text


async def send_email(*, to: str, template: str, context: dict[str, Any]) -> None:
    if settings.email_provider != "ses":
        log.info("notification.email", to=to, template=template,
                 context_keys=sorted(context))
        return
    if not settings.email_from_address:
        raise EmailDeliveryFailed("EMAIL_FROM_ADDRESS is not configured")
    subject, body = render(template, context)
    try:
        await asyncio.to_thread(_ses_send, to=to, subject=subject, body=body)
    except Exception as exc:  # boto/botocore raise many types; map to one AppError
        if _is_suppressed_recipient(exc):
            # Distinct log event on purpose: this is the signal that bounce /
            # complaint handling is actually working, and it is what to show
            # when asking AWS to re-review production access.
            log.warning("notification.email_suppressed", template=template,
                        error=type(exc).__name__)
            raise EmailSuppressed("recipient is suppressed after a bounce or complaint") from exc
        log.error("notification.email_failed", to=to, template=template,
                  error=type(exc).__name__)
        raise EmailDeliveryFailed("could not send email") from exc
    log.info("notification.email_sent", to=to, template=template)


async def send_sms(*, to: str, body: str) -> None:
    log.info("notification.sms", to=to)
