"""Plans endpoint.

`GET /plans` is public — no JWT — but still requires `X-Product-Slug` to
scope the listing. Mutations require platform-write permission via JWT.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, RequireProduct, require_permission
from app.schemas.plan import PlanCreate, PlanResponse, PlanUpdate
from app.services import plan as plan_svc

router = APIRouter()


@router.get("", response_model=list[PlanResponse])
async def list_plans(
    product_id: RequireProduct,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    return await plan_svc.list_plans(db, product_id=product_id, only_public=True)


@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("plans:write"))])
async def create_plan(
    payload: PlanCreate, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> object:
    return await plan_svc.create_plan(
        db, payload, product_id=user.product_id, actor_user_id=user.id,
    )


@router.patch("/{code}", response_model=PlanResponse,
              dependencies=[Depends(require_permission("plans:write"))])
async def update_plan(
    code: str,
    payload: PlanUpdate,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> object:
    return await plan_svc.update_plan(
        db, code, payload, product_id=user.product_id, actor_user_id=user.id,
    )
