"""Shared fixtures: schema setup, async HTTP client, per-test cleanup.

The whole suite runs on a single event loop (session-scoped) because the
async SQLAlchemy engine pools connections that are pinned to the loop they
were opened on.

Two products are seeded once per session — `producta` (default for helpers)
and `productb` (used in cross-product isolation tests). Each gets its own
plans + system roles.
"""

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest_asyncio

# Force test config BEFORE any app module is imported.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://platform:platform@localhost:5432/platform_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["JWT_SECRET"] = "test-secret-please-change-this-is-32+chars"
os.environ["BILLING_PROVIDER"] = "mock"
os.environ["APP_ENV"] = "test"
os.environ["APP_DEBUG"] = "false"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"  # effectively disable for tests
os.environ["PLATFORM_ADMIN_TOKEN"] = "test-platform-admin-token"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import engine, session_scope  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.tenant import bypass_product, bypass_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.plan import BillingInterval, Plan, PlanFeature  # noqa: E402
from app.models.product import Product, ProductStatus  # noqa: E402
from app.services import product as product_svc  # noqa: E402
from app.services import rbac  # noqa: E402

# Tables wiped between tests (tenant + product data + audit etc).
TENANT_TABLES = (
    "audit_log",
    "credit_ledger",
    "credit_wallets",
    "idempotency_keys",
    "invoices",
    "password_reset_tokens",
    "refresh_tokens",
    "user_roles",
    "subscriptions",
    "users",
    "tenants",
)
# Tables preserved between tests (platform catalog + products themselves).
CATALOG_TABLES = (
    "plans", "plan_features", "permissions", "roles", "role_permissions", "products",
)

PRODUCT_SLUGS = ("producta", "productb")
PRODUCT_IDS: dict[str, UUID] = {}


PLAN_TEMPLATE = [
    ("free",       "Free",       0,    0,  True,  [
        ("seats", Decimal("3"), None),
        ("credits.ai_completion", None, Decimal("100")),
    ]),
    ("pro",        "Pro",        2900, 14, True,  [
        ("seats", Decimal("25"), None),
        ("credits.ai_completion", None, Decimal("10000")),
    ]),
    ("enterprise", "Enterprise", 49900, 30, False, [
        ("seats", None, None),
        ("credits.ai_completion", None, Decimal("250000")),
    ]),
]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_scope() as db:
        with bypass_product(), bypass_tenant():
            for slug in PRODUCT_SLUGS:
                product = Product(
                    name=slug.title(), slug=slug,
                    status=ProductStatus.ACTIVE, is_active=True,
                )
                db.add(product)
                await db.flush()
                PRODUCT_IDS[slug] = product.id

                await rbac.ensure_system_roles_for_product(db, product_id=product.id)

                for code, name, price, trial, public, features in PLAN_TEMPLATE:
                    plan = Plan(
                        product_id=product.id, code=code, name=name,
                        price_cents=price, interval=BillingInterval.MONTH,
                        trial_days=trial, is_public=public,
                    )
                    db.add(plan)
                    await db.flush()
                    for fkey, limit, credit in features:
                        db.add(PlanFeature(
                            product_id=product.id, plan_id=plan.id,
                            feature_key=fkey, limit_value=limit, credit_amount=credit,
                        ))

    # Warm the slug→id cache (and clear any stale entries from previous runs).
    redis = get_redis()
    await redis.flushdb()
    await redis.aclose()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tenant_data() -> AsyncIterator[None]:
    """Wipe tenant data between tests; preserve the platform catalog + products."""
    yield
    async with engine.begin() as conn:
        await conn.execute(text(
            f"TRUNCATE {', '.join(TENANT_TABLES)} RESTART IDENTITY CASCADE"
        ))
    redis = get_redis()
    await redis.flushdb()
    await redis.aclose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------- helpers ----------------------------------------------------------

def product_headers(product_slug: str = "producta") -> dict[str, str]:
    return {"X-Product-Slug": product_slug}


def auth(token: str, product_slug: str = "producta") -> dict[str, str]:
    """Authorization + product headers — both needed for any authenticated call.

    The product header is redundant with the JWT `pid` claim, but the
    middleware verifies they match so we send it explicitly for realism.
    Tests can omit it (auth() returns just Authorization) when probing
    the JWT-only path."""
    return {"Authorization": f"Bearer {token}", **product_headers(product_slug)}


def auth_no_product_header(token: str) -> dict[str, str]:
    """Auth header without product slug — relies on JWT pid claim alone."""
    return {"Authorization": f"Bearer {token}"}


def auth_acting_as(
    token: str, child_slug: str, product_slug: str = "producta"
) -> dict[str, str]:
    """Auth headers plus `X-Acting-Tenant-Slug` for parent → child switching."""
    return {**auth(token, product_slug), "X-Acting-Tenant-Slug": child_slug}


def platform_admin_headers() -> dict[str, str]:
    return {"X-Platform-Admin-Token": "test-platform-admin-token"}


async def register_tenant(
    client: AsyncClient,
    *,
    slug: str,
    email: str | None = None,
    password: str = "S3cretPassword!",
    tenant_name: str | None = None,
    product_slug: str = "producta",
) -> dict:
    """Helper: register a new tenant + owner inside `product_slug`, return token payload."""
    payload = {
        "tenant_name": tenant_name or slug.title(),
        "tenant_slug": slug,
        "email": email or f"owner@{slug}.example.com",
        "password": password,
        "full_name": "Owner",
    }
    r = await client.post(
        "/api/v1/auth/register", json=payload, headers=product_headers(product_slug),
    )
    assert r.status_code == 201, r.text
    return r.json()


def product_id(slug: str) -> UUID:
    return PRODUCT_IDS[slug]
