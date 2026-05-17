"""Seed default product + plans + a root tenant + an admin user.

Idempotent: re-runs are safe.
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.database import session_scope
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.core.tenant import bypass_product, bypass_tenant, set_current_product, set_current_tenant
from app.models.plan import BillingInterval, Plan, PlanFeature
from app.models.product import Product, ProductStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.services import rbac
from app.services.subscription import start_trial

log = get_logger("seed")

DEFAULT_PRODUCT_SLUG = "platform"
DEFAULT_PRODUCT_NAME = "Default Product"

DEFAULT_PLANS = [
    {
        "code": "free",
        "name": "Free",
        "price_cents": 0,
        "interval": BillingInterval.MONTH,
        "trial_days": 0,
        "features": [
            {"feature_key": "seats", "limit_value": Decimal("3"), "credit_amount": None},
            {"feature_key": "credits.ai_completion", "credit_amount": Decimal("100"), "limit_value": None},
        ],
    },
    {
        "code": "pro",
        "name": "Pro",
        "price_cents": 2900,
        "interval": BillingInterval.MONTH,
        "trial_days": 14,
        "features": [
            {"feature_key": "seats", "limit_value": Decimal("25"), "credit_amount": None},
            {"feature_key": "credits.ai_completion", "credit_amount": Decimal("10000"), "limit_value": None},
            {"feature_key": "storage.gb", "limit_value": Decimal("100"), "credit_amount": None},
        ],
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "price_cents": 49900,
        "interval": BillingInterval.MONTH,
        "trial_days": 30,
        "is_public": False,
        "features": [
            {"feature_key": "seats", "limit_value": None, "credit_amount": None},
            {"feature_key": "credits.ai_completion", "credit_amount": Decimal("250000"), "limit_value": None},
            {"feature_key": "storage.gb", "limit_value": Decimal("1000"), "credit_amount": None},
        ],
    },
]


async def main() -> None:
    configure_logging()
    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            product = await db.scalar(
                select(Product).where(Product.slug == DEFAULT_PRODUCT_SLUG)
            )
            if product is None:
                product = Product(
                    name=DEFAULT_PRODUCT_NAME, slug=DEFAULT_PRODUCT_SLUG,
                    status=ProductStatus.ACTIVE, is_active=True,
                )
                db.add(product)
                await db.flush()
                log.info("seed.product_created", slug=product.slug)

            await rbac.ensure_system_roles_for_product(db, product_id=product.id)

            for p in DEFAULT_PLANS:
                existing = await db.scalar(
                    select(Plan).where(Plan.product_id == product.id, Plan.code == p["code"])
                )
                if existing:
                    continue
                plan = Plan(
                    product_id=product.id,
                    code=p["code"], name=p["name"], price_cents=p["price_cents"],
                    interval=p["interval"], trial_days=p["trial_days"],
                    is_public=p.get("is_public", True),
                )
                db.add(plan)
                await db.flush()
                for f in p["features"]:
                    db.add(PlanFeature(plan_id=plan.id, product_id=product.id, **f))
                log.info("seed.plan_created", product=product.slug, code=p["code"])

            root = await db.scalar(
                select(Tenant).where(Tenant.product_id == product.id, Tenant.slug == "platform")
            )
            if root is None:
                root = Tenant(
                    product_id=product.id, name="Platform Root",
                    slug="platform", is_root=True,
                )
                db.add(root)
                await db.flush()
                log.info("seed.root_tenant_created")

            set_current_product(product.id)
            set_current_tenant(root.id)
            admin = await db.scalar(
                select(User).where(
                    User.product_id == product.id,
                    User.tenant_id == root.id,
                    User.email == "admin@example.com",
                )
            )
            if admin is None:
                admin = User(
                    product_id=product.id, tenant_id=root.id,
                    email="admin@example.com",
                    password_hash=hash_password("ChangeMeNow123!"),
                    full_name="Platform Admin",
                    is_active=True, is_verified=True,
                )
                db.add(admin)
                await db.flush()
                await rbac.assign_role_by_name(db, user=admin, role_name="owner")
                log.info("seed.admin_created", email=admin.email)

            try:
                await start_trial(db, tenant_id=root.id, product_id=product.id, plan_code="pro")
            except Exception as exc:
                log.info("seed.trial_skipped", reason=str(exc))


if __name__ == "__main__":
    asyncio.run(main())
