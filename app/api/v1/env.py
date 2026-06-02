"""Product-scoped env-vars fetch.

Mounted at ``/env``. Authenticated by a per-product service token
(``X-Service-Token: pst_…``). The token implies a product — no
``X-Product-Slug`` header needed, though if present it must agree
(defence in depth in ``require_service_token``).

Use case: a product's BACKEND boots, fetches its secrets, and holds
them in memory for the process lifetime. Never put this token on a
client (browser / mobile / Electron renderer) — by definition it
hands back plaintext secrets.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_service_token
from app.models.service_token import ProductServiceToken
from app.services import env_var as env_svc

router = APIRouter()


@router.get(
    "",
    summary="Fetch every env var for the product behind the service token",
)
async def get_product_env(
    token: Annotated[
        ProductServiceToken,
        Depends(require_service_token("env:read")),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Return ``{KEY: value, ...}`` for the calling product.

    All values are returned in plaintext (decrypted on the fly for
    is_secret rows). The keys are sorted for stable iteration on the
    consumer side.
    """
    rows = await env_svc.list_vars(db, product_id=token.product_id)
    return {r.key: env_svc.reveal(r) for r in rows}
