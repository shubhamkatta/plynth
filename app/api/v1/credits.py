from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, require_permission
from app.core.tenant import current_tenant_id
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
) -> list:
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
) -> list:
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
