"""Server-side Google OAuth token exchange.

Why this lives on the platform
    Per-install client_secret leakage is unavoidable when products ship
    desktop apps with the secret in their package or fetch it via /env.
    This endpoint keeps the secret on the platform: clients send the
    PKCE-protected ``code`` (or a refresh token) + ``client_id``, the
    platform looks up the matching secret in the per-product env vault,
    swaps with Google, and returns Google's response verbatim.

Lookup convention
    The vault key naming convention is ``GOOGLE_*CLIENT_ID`` and
    ``GOOGLE_*CLIENT_SECRET``. We enumerate every ``GOOGLE_*CLIENT_ID``
    env var for the product, match the request's ``client_id`` to one
    of those values, and read the secret from the same key with
    ``_CLIENT_ID`` replaced by ``_CLIENT_SECRET``.

    Examples for mayva:
      GOOGLE_CLIENT_ID         ↔ GOOGLE_CLIENT_SECRET
      GOOGLE_GMAIL_CLIENT_ID   ↔ GOOGLE_GMAIL_CLIENT_SECRET

Privacy
    Tokens are pass-through. The platform never persists ``code``,
    ``code_verifier``, ``refresh_token``, ``access_token``, or the
    Google client_secret. Logs include product/client_id/grant_type/
    outcome only — never secret material.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Unauthorized, ValidationFailed
from app.services import env_var as env_svc

log = structlog.get_logger("integrations.google")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleUpstreamError(AppError):
    """Google's token endpoint was unreachable / returned 5xx. 503."""

    status_code = 503
    code = "service_unavailable"


async def _find_client_secret(
    db: AsyncSession, *, product_id: UUID, client_id: str
) -> str:
    """Resolve the vault secret matching ``client_id``.

    Iterates every ``GOOGLE_*CLIENT_ID`` env var for the product,
    decrypts each, and compares to the request's ``client_id``. The
    matching row's key name (with ``CLIENT_ID`` → ``CLIENT_SECRET``)
    is the secret we want.

    Why iterate rather than encode the client_id into the key name:
    keeps the operator-facing key names familiar (``GOOGLE_CLIENT_ID``
    looks like an env var) and avoids forcing operators to embed a
    long opaque client_id into a key string.
    """
    rows = await env_svc.list_vars(db, product_id=product_id)
    candidates: list[tuple[str, str]] = []  # (id_key, secret_key)
    for r in rows:
        if not (r.key.startswith("GOOGLE_") and r.key.endswith("_CLIENT_ID")):
            continue
        secret_key = r.key.removesuffix("_CLIENT_ID") + "_CLIENT_SECRET"
        candidates.append((r.key, secret_key))

    for id_key, secret_key in candidates:
        try:
            id_row = await env_svc.get_var(db, product_id=product_id, key=id_key)
            if env_svc.reveal(id_row) == client_id:
                secret_row = await env_svc.get_var(db, product_id=product_id, key=secret_key)
                return env_svc.reveal(secret_row)
        except Exception:
            # Decryption / lookup failure on this candidate is not fatal
            # for the search — continue checking the others. The actual
            # failure (no match) surfaces as ValidationFailed below.
            continue

    raise ValidationFailed(
        "unknown client_id for this product",
        details={"client_id_tail": client_id[-16:] if len(client_id) > 16 else client_id},
    )


async def exchange_with_google(
    *,
    request_id: str,
    product_id: UUID,
    client_id: str,
    grant_type: str,
    form_body: dict[str, str],
) -> dict[str, Any]:
    """POST ``form_body`` to Google's token endpoint, raise platform
    exceptions mapped per the spec's error matrix."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(GOOGLE_TOKEN_URL, data=form_body)
    except httpx.HTTPError as exc:
        log.warning(
            "google.exchange.network_error",
            request_id=request_id,
            product_id=str(product_id),
            client_id_tail=client_id[-16:],
            grant_type=grant_type,
            error=type(exc).__name__,
        )
        raise GoogleUpstreamError("google token endpoint unreachable") from exc

    if response.status_code >= 500:
        log.warning(
            "google.exchange.upstream_5xx",
            request_id=request_id,
            product_id=str(product_id),
            client_id_tail=client_id[-16:],
            grant_type=grant_type,
            google_status=response.status_code,
        )
        raise GoogleUpstreamError(
            "google token endpoint returned 5xx",
            details={"google_status": response.status_code},
        )

    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = {}
        google_error = (body.get("error") or "unknown") if isinstance(body, dict) else "unknown"
        log.warning(
            "google.exchange.rejected",
            request_id=request_id,
            product_id=str(product_id),
            client_id_tail=client_id[-16:],
            grant_type=grant_type,
            google_status=response.status_code,
            google_error=google_error,
        )
        # 401-class envelope per spec, with Google's `error` code in the
        # message so clients can branch on "re-auth needed" etc.
        raise Unauthorized(
            f"google: {google_error}",
            details={"google_status": response.status_code, "google_error": google_error},
        )

    try:
        token_body = response.json()
    except ValueError as exc:
        log.warning(
            "google.exchange.bad_response",
            request_id=request_id,
            product_id=str(product_id),
            client_id_tail=client_id[-16:],
            grant_type=grant_type,
        )
        raise GoogleUpstreamError("google response was not JSON") from exc

    if not isinstance(token_body, dict) or "access_token" not in token_body:
        log.warning(
            "google.exchange.missing_access_token",
            request_id=request_id,
            product_id=str(product_id),
            client_id_tail=client_id[-16:],
            grant_type=grant_type,
        )
        raise GoogleUpstreamError("google response missing access_token")

    log.info(
        "google.exchange.ok",
        request_id=request_id,
        product_id=str(product_id),
        client_id_tail=client_id[-16:],
        grant_type=grant_type,
        scope_present="scope" in token_body,
        refresh_token_present="refresh_token" in token_body,
    )
    return token_body
