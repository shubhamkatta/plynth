"""Notification provider stub. Swap with SES / Postmark / Twilio in production.

Intentionally a no-op: the platform only emits events; delivery is your choice.
"""

from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


async def send_email(*, to: str, template: str, context: dict[str, Any]) -> None:
    log.info("notification.email", to=to, template=template, **context)


async def send_sms(*, to: str, body: str) -> None:
    log.info("notification.sms", to=to, body=body)
