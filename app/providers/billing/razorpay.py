"""Razorpay driver (India). Implements the provider-neutral `BillingProvider`.

Mirrors `stripe.py`'s structure but talks to Razorpay's REST API over httpx
(Basic auth: key_id:key_secret) rather than a vendor SDK — Razorpay's
subscription model maps cleanly onto the neutral DTOs:

- customers        → POST /v1/customers (idempotent-ish: create, reuse on dup)
- subscriptions    → POST /v1/subscriptions (a Razorpay *plan_id* is our price_id)
- change / cancel  → POST /v1/subscriptions/{id} ... / .../cancel
- webhook          → HMAC-SHA256(raw_body, webhook_secret) hex, compared against
                     the `X-Razorpay-Signature` header. NEVER trust a raw body.

Two conventions match the Stripe driver:
- pass an idempotency key on mutating calls (Razorpay honours `X-Razorpay-*`
  idempotency via the header) to defend against retries;
- the webhook handler MUST verify the signature before parsing.

Amounts on the wire are the smallest currency unit (paise); the neutral DTO's
`amount_cents` carries that integer unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.providers.billing.base import (
    BillingProvider,
    ProviderCustomer,
    ProviderInvoice,
    ProviderSubscription,
    WebhookEvent,
)

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


def _ts(ts: int | None) -> datetime:
    return datetime.fromtimestamp(ts or 0, tz=UTC)


class RazorpayBillingProvider(BillingProvider):
    name = "razorpay"

    def __init__(self) -> None:
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET missing")
        token = f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()
        self._auth = base64.b64encode(token).decode()

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Basic {self._auth}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Razorpay-Idempotency"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                f"{RAZORPAY_API_BASE}{path}",
                json=json_body,
                params=params,
                headers=self._headers(idempotency_key),
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"razorpay {method} {path} failed: {resp.status_code} {resp.text}")
        return dict(resp.json())

    async def ensure_customer(self, *, tenant_id: str, email: str) -> ProviderCustomer:
        # Razorpay has no metadata-search; fail_existing=0 returns the existing
        # customer instead of erroring when the email is already registered.
        data = await self._request(
            "POST",
            "/customers",
            json_body={"email": email, "notes": {"tenant_id": tenant_id}, "fail_existing": 0},
        )
        return ProviderCustomer(id=str(data["id"]), email=str(data.get("email") or email))

    async def create_subscription(
        self,
        *,
        customer_id: str,
        price_id: str,
        trial_days: int,
        payment_method_token: str | None,
        idempotency_key: str | None,
    ) -> ProviderSubscription:
        # `price_id` is a Razorpay plan_id. total_count is required; a large
        # value approximates an open-ended subscription.
        body: dict[str, Any] = {
            "plan_id": price_id,
            "customer_id": customer_id,
            "total_count": 120,
            "customer_notify": 1,
        }
        if trial_days:
            body["start_at"] = int(datetime.now(UTC).timestamp()) + trial_days * 86400
        data = await self._request(
            "POST", "/subscriptions", json_body=body, idempotency_key=idempotency_key
        )
        return self._sub(data)

    async def change_subscription(
        self,
        *,
        subscription_id: str,
        new_price_id: str,
        proration: bool,
        idempotency_key: str | None,
    ) -> ProviderSubscription:
        data = await self._request(
            "PATCH",
            f"/subscriptions/{subscription_id}",
            json_body={
                "plan_id": new_price_id,
                "schedule_change_at": "now" if proration else "cycle_end",
            },
            idempotency_key=idempotency_key,
        )
        return self._sub(data)

    async def cancel_subscription(
        self, *, subscription_id: str, at_period_end: bool
    ) -> ProviderSubscription:
        data = await self._request(
            "POST",
            f"/subscriptions/{subscription_id}/cancel",
            json_body={"cancel_at_cycle_end": 1 if at_period_end else 0},
        )
        return self._sub(data)

    async def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        secret = settings.razorpay_webhook_secret
        if not secret:
            raise RuntimeError("RAZORPAY_WEBHOOK_SECRET missing")
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            raise RuntimeError("razorpay webhook signature verification failed")
        body = json.loads(payload)
        # Razorpay nests the entity under payload.<type>.entity; hand the whole
        # `payload` block to the caller (mirrors Stripe's data.object shape).
        return WebhookEvent(
            id=str(body.get("id") or body.get("account_id") or "evt_razorpay"),
            type=str(body["event"]),
            data=body.get("payload", {}),
        )

    async def retry_invoice(self, *, invoice_id: str) -> ProviderInvoice:
        data = await self._request("GET", f"/invoices/{invoice_id}")
        return ProviderInvoice(
            id=str(data["id"]),
            customer_id=str(data.get("customer_id") or ""),
            subscription_id=data.get("subscription_id"),
            amount_cents=int(data.get("amount") or 0),
            currency=str(data.get("currency") or "INR").upper(),
            status=str(data.get("status") or "issued"),
            hosted_url=data.get("short_url"),
            issued_at=_ts(data.get("issued_at") or data.get("created_at")),
            due_at=_ts(data.get("expire_by") or data.get("created_at")),
        )

    @staticmethod
    def _sub(sub: dict[str, Any]) -> ProviderSubscription:
        # Razorpay statuses: created/authenticated/active/paused/halted/
        # cancelled/completed/expired. current_start/end are epoch seconds.
        return ProviderSubscription(
            id=str(sub["id"]),
            customer_id=str(sub.get("customer_id") or ""),
            price_id=str(sub.get("plan_id") or ""),
            status=str(sub.get("status") or "created"),
            current_period_start=_ts(sub.get("current_start")),
            current_period_end=_ts(sub.get("current_end")),
            cancel_at_period_end=bool(sub.get("cancel_at_cycle_end") or False),
        )
