"""Platform integrations passthroughs.

Mounted at ``/integrations``. Each endpoint authenticates with the
per-product ``X-Service-Token`` (NOT a user JWT) and performs a
narrowly-scoped server-side operation using a secret held in the
product's env vault.

Today: Google OAuth code/refresh exchange.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_service_token
from app.models.service_token import ProductServiceToken
from app.schemas.integrations import (
    GoogleExchangeCodeRequest,
    GoogleExchangeRefreshRequest,
    GoogleExchangeRequest,
    GoogleExchangeResponse,
)
from app.services import google_oauth

router = APIRouter()

log = structlog.get_logger("integrations.google")


@router.post(
    "/google/exchange",
    response_model=GoogleExchangeResponse,
    summary="Server-side Google OAuth code / refresh-token exchange",
)
async def google_exchange(
    payload: GoogleExchangeRequest,
    token: Annotated[
        ProductServiceToken,
        Depends(require_service_token("google:exchange")),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ] = None,
) -> GoogleExchangeResponse:
    """Swap a one-time auth code (or refresh token) for Google tokens.

    The product's client_secret lives in the platform's env vault keyed
    by the matching ``client_id``. The client_secret never leaves the
    platform; the response is whatever Google returned (verbatim).

    See ``docs/INTEGRATION.md`` § 9.5 for the contract.
    """
    request_id = structlog.contextvars.get_contextvars().get("request_id", "")
    client_secret = await google_oauth._find_client_secret(
        db, product_id=token.product_id, client_id=payload.client_id,
    )

    form: dict[str, str] = {
        "grant_type":    payload.grant_type,
        "client_id":     payload.client_id,
        "client_secret": client_secret,
    }
    if isinstance(payload, GoogleExchangeCodeRequest):
        form["code"]          = payload.code
        form["redirect_uri"]  = payload.redirect_uri
        form["code_verifier"] = payload.code_verifier
    else:
        assert isinstance(payload, GoogleExchangeRefreshRequest)
        form["refresh_token"] = payload.refresh_token

    log.info(
        "google.exchange.request",
        request_id=request_id,
        product_id=str(token.product_id),
        client_id_tail=payload.client_id[-16:],
        grant_type=payload.grant_type,
        idempotency_key_present=idempotency_key is not None,
    )

    token_body = await google_oauth.exchange_with_google(
        request_id=request_id,
        product_id=token.product_id,
        client_id=payload.client_id,
        grant_type=payload.grant_type,
        form_body=form,
    )
    return GoogleExchangeResponse.model_validate(token_body)
