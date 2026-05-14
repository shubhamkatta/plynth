"""Credit ledger: atomic grant + consume.

Every wallet + ledger entry is scoped to (product, tenant). Callers must
pass `product_id` so the row carries it; internal lookups go through the
same context.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientCredits, NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.credit import CreditEntryType, CreditLedger, CreditWallet
from app.models.plan import Plan, PlanFeature
from app.services import audit


async def _get_or_create_wallet(
    db: AsyncSession, *, tenant_id: UUID, product_id: UUID, feature_key: str
) -> CreditWallet:
    wallet = await db.scalar(
        select(CreditWallet).where(
            CreditWallet.tenant_id == tenant_id,
            CreditWallet.feature_key == feature_key,
        )
    )
    if wallet is None:
        wallet = CreditWallet(
            product_id=product_id, tenant_id=tenant_id,
            feature_key=feature_key, balance=Decimal("0"),
        )
        db.add(wallet)
        await db.flush()
    return wallet


async def _lock_wallet(
    db: AsyncSession, *, tenant_id: UUID, feature_key: str
) -> CreditWallet:
    wallet = await db.scalar(
        select(CreditWallet)
        .where(CreditWallet.tenant_id == tenant_id, CreditWallet.feature_key == feature_key)
        .with_for_update()
    )
    if wallet is None:
        raise NotFound(f"wallet {feature_key!r} not found")
    return wallet


async def _was_referenced(db: AsyncSession, *, wallet_id: UUID, reference: str) -> bool:
    return bool(
        await db.scalar(
            select(CreditLedger.id).where(
                CreditLedger.wallet_id == wallet_id, CreditLedger.reference == reference
            )
        )
    )


async def grant(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    feature_key: str,
    amount: Decimal,
    reason: str | None = None,
    reference: str | None = None,
    entry_type: CreditEntryType = CreditEntryType.GRANT,
) -> CreditWallet:
    with bypass_product(), bypass_tenant():
        wallet = await _get_or_create_wallet(
            db, tenant_id=tenant_id, product_id=product_id, feature_key=feature_key,
        )
        if reference and await _was_referenced(db, wallet_id=wallet.id, reference=reference):
            return wallet
        wallet.balance += amount
        db.add(
            CreditLedger(
                product_id=product_id,
                tenant_id=tenant_id,
                wallet_id=wallet.id,
                entry_type=entry_type,
                amount=amount,
                balance_after=wallet.balance,
                reason=reason,
                reference=reference,
            )
        )
        await db.flush()
    return wallet


async def consume(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    feature_key: str,
    amount: Decimal,
    reason: str | None = None,
    reference: str | None = None,
) -> CreditWallet:
    if amount <= 0:
        raise ValueError("amount must be positive")
    with bypass_product(), bypass_tenant():
        wallet = await _lock_wallet(db, tenant_id=tenant_id, feature_key=feature_key)
        if wallet.product_id != product_id:
            raise NotFound("wallet not in current product")
        if reference and await _was_referenced(db, wallet_id=wallet.id, reference=reference):
            return wallet
        if wallet.balance < amount:
            raise InsufficientCredits(
                f"need {amount} {feature_key}, have {wallet.balance}",
                details={"feature_key": feature_key, "needed": str(amount),
                         "balance": str(wallet.balance)},
            )
        wallet.balance -= amount
        db.add(
            CreditLedger(
                product_id=product_id,
                tenant_id=tenant_id,
                wallet_id=wallet.id,
                entry_type=CreditEntryType.DEBIT,
                amount=-amount,
                balance_after=wallet.balance,
                reason=reason,
                reference=reference,
            )
        )
        await db.flush()
    return wallet


async def grant_plan_credits(
    db: AsyncSession, *, tenant_id: UUID, product_id: UUID, plan: Plan, reference: str
) -> None:
    """Issue every PlanFeature.credit_amount as a wallet grant.

    `reference` should include the period start date so calling this on the
    same period twice is a no-op."""
    features: list[PlanFeature] = list(plan.features)
    if not features and plan.id:
        features = list(
            (
                await db.scalars(select(PlanFeature).where(PlanFeature.plan_id == plan.id))
            ).all()
        )
    for feat in features:
        if feat.credit_amount and feat.credit_amount > 0:
            await grant(
                db,
                tenant_id=tenant_id,
                product_id=product_id,
                feature_key=feat.feature_key,
                amount=Decimal(feat.credit_amount),
                reason=f"plan:{plan.code}",
                reference=f"{reference}:{feat.feature_key}",
            )


async def reset_period(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    product_id: UUID,
    feature_key: str,
    actor_user_id: UUID | None = None,
) -> CreditWallet:
    """Zero out the wallet at period rollover. Records an EXPIRY entry."""
    with bypass_product(), bypass_tenant():
        wallet = await _lock_wallet(db, tenant_id=tenant_id, feature_key=feature_key)
        if wallet.product_id != product_id:
            raise NotFound("wallet not in current product")
        if wallet.balance == 0:
            return wallet
        expired = wallet.balance
        wallet.balance = Decimal("0")
        wallet.period_start = datetime.now(UTC)
        wallet.period_end = wallet.period_start + timedelta(days=30)
        db.add(
            CreditLedger(
                product_id=product_id,
                tenant_id=tenant_id,
                wallet_id=wallet.id,
                entry_type=CreditEntryType.EXPIRY,
                amount=-expired,
                balance_after=Decimal("0"),
                reason="period_reset",
            )
        )
        await audit.record(
            db, action="credits.period_reset", actor_user_id=actor_user_id,
            resource_type="credit_wallet", resource_id=wallet.id,
            tenant_id=tenant_id, product_id=product_id,
            diff={"feature_key": feature_key, "expired": str(expired)},
        )
    return wallet
