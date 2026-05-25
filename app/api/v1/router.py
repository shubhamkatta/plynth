from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    credits,
    jobs,
    plans,
    roles,
    storage,
    subscriptions,
    tenants,
    users,
    webhooks,
    webhooks_admin,
)

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(tenants.router, prefix="/tenants", tags=["tenants"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(subscriptions.router, prefix="/subscription", tags=["subscription"])
api_router.include_router(credits.router, prefix="/credits", tags=["credits"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(storage.router, prefix="/storage", tags=["storage"])
api_router.include_router(
    webhooks_admin.router,
    prefix="/admin/products/{slug}/webhooks",
    tags=["webhooks-admin"],
)
