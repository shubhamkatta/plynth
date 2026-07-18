from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission, require_service_token
from app.core.tenant import current_tenant_id
from app.models.service_token import ProductServiceToken
from app.models.credit import CreditLedger, CreditWallet
from app.schemas.credit import (
    CreditConsumeRequest,
    CreditGrantRequest,
    CreditLedgerEntry,
    CreditWalletResponse,
)
from app.services import credit as credit_svc

router = APIRouter()


@router.get("/wallets", response_model=list[CreditWalletResponse],
            dependencies=[Depends(require_permission("credits:read"))])
async def list_wallets(
    user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[CreditWallet]:
    tid = current_tenant_id() or user.tenant_id
    return list((await db.scalars(
        select(CreditWallet).where(
            CreditWallet.product_id == user.product_id,
            CreditWallet.tenant_id == tid,
        )
    )).all())


@router.get("/ledger", response_model=list[CreditLedgerEntry],
            dependencies=[Depends(require_permission("credits:read"))])
async def ledger(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
) -> list[CreditLedger]:
    tid = current_tenant_id() or user.tenant_id
    return list((await db.scalars(
        select(CreditLedger)
        .where(
            CreditLedger.product_id == user.product_id,
            CreditLedger.tenant_id == tid,
        )
        .order_by(CreditLedger.created_at.desc())
        .limit(limit)
    )).all())


@router.post("/consume", response_model=CreditWalletResponse,
             status_code=status.HTTP_200_OK,
             dependencies=[Depends(require_permission("credits:consume"))])
async def consume(
    payload: CreditConsumeRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreditWallet:
    return await credit_svc.consume(
        db,
        product_id=user.product_id,
        tenant_id=current_tenant_id() or user.tenant_id,
        feature_key=payload.feature_key,
        amount=payload.amount,
        reason=payload.reason,
        reference=payload.reference,
    )


@router.post("/service/consume", response_model=CreditWalletResponse,
             status_code=status.HTTP_200_OK)
async def service_consume(
    payload: CreditConsumeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[
        ProductServiceToken, Depends(require_service_token("credits:consume"))
    ],
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
) -> CreditWallet:
    """Machine credit consumption for a product backend (e.g. metering an AI
    action from a webhook, where there is no end-user JWT). Authenticated by a
    ``pst_`` service token scoped ``credits:consume``; the product comes from the
    token and the tenant from the ``X-Tenant-ID`` header. Mirrors ``/consume``."""
    return await credit_svc.consume(
        db,
        product_id=token.product_id,
        tenant_id=UUID(x_tenant_id),
        feature_key=payload.feature_key,
        amount=payload.amount,
        reason=payload.reason,
        reference=payload.reference,
    )


@router.post("/grant", response_model=CreditWalletResponse,
             status_code=status.HTTP_200_OK,
             dependencies=[Depends(require_permission("credits:grant"))])
async def grant(
    payload: CreditGrantRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreditWallet:
    return await credit_svc.grant(
        db,
        product_id=user.product_id,
        tenant_id=current_tenant_id() or user.tenant_id,
        feature_key=payload.feature_key,
        amount=payload.amount,
        reason=payload.reason,
        reference=payload.reference,
    )
