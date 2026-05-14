"""Plan catalog management. Plans are per-product."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import Conflict, NotFound
from app.core.tenant import bypass_product, bypass_tenant
from app.models.plan import Plan, PlanFeature
from app.schemas.plan import PlanCreate, PlanUpdate
from app.services import audit


async def list_plans(
    db: AsyncSession, *, product_id: UUID, only_public: bool = True
) -> list[Plan]:
    with bypass_product(), bypass_tenant():
        stmt = (
            select(Plan)
            .options(selectinload(Plan.features))
            .where(Plan.product_id == product_id, Plan.is_active.is_(True))
        )
        if only_public:
            stmt = stmt.where(Plan.is_public.is_(True))
        return list((await db.scalars(stmt)).all())


async def get_by_code(db: AsyncSession, *, product_id: UUID, code: str) -> Plan:
    with bypass_product(), bypass_tenant():
        plan = await db.scalar(
            select(Plan)
            .options(selectinload(Plan.features))
            .where(Plan.product_id == product_id, Plan.code == code)
        )
    if plan is None:
        raise NotFound(f"plan {code!r} not found in product")
    return plan


async def create_plan(
    db: AsyncSession, data: PlanCreate, *, product_id: UUID, actor_user_id: UUID | None = None
) -> Plan:
    with bypass_product(), bypass_tenant():
        if await db.scalar(
            select(Plan).where(Plan.product_id == product_id, Plan.code == data.code)
        ):
            raise Conflict(f"plan code {data.code!r} already exists in this product")
        plan = Plan(
            product_id=product_id,
            code=data.code,
            name=data.name,
            description=data.description,
            price_cents=data.price_cents,
            currency=data.currency,
            interval=data.interval,
            trial_days=data.trial_days,
            is_public=data.is_public,
            provider_refs=data.provider_refs,
        )
        db.add(plan)
        await db.flush()
        for feat in data.features:
            db.add(PlanFeature(plan_id=plan.id, product_id=product_id, **feat.model_dump()))
        await db.flush()
        await db.refresh(plan, attribute_names=["features"])
        await audit.record(
            db, action="plan.create", actor_user_id=actor_user_id,
            resource_type="plan", resource_id=plan.id, product_id=product_id,
            diff={"code": plan.code, "price_cents": plan.price_cents},
        )
    return plan


async def update_plan(
    db: AsyncSession,
    code: str,
    data: PlanUpdate,
    *,
    product_id: UUID,
    actor_user_id: UUID | None = None,
) -> Plan:
    plan = await get_by_code(db, product_id=product_id, code=code)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(plan, k, v)
    await db.flush()
    with bypass_product(), bypass_tenant():
        await audit.record(
            db, action="plan.update", actor_user_id=actor_user_id,
            resource_type="plan", resource_id=plan.id, product_id=product_id,
            diff={"changes": changes},
        )
    return plan
