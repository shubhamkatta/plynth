from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    components,
    components_admin,
    credits,
    env,
    env_admin,
    integrations,
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
# Per-product env-vars vault — admin CRUD + service tokens.
api_router.include_router(
    env_admin.router,
    prefix="/admin/products/{slug}",
    tags=["env-admin"],
)
# Product-runtime fetch — authenticated by X-Service-Token (pst_…).
api_router.include_router(env.router, prefix="/env", tags=["env"])
# Per-product components catalog (admin) + user override management.
api_router.include_router(
    components_admin.router,
    prefix="/admin/products/{slug}/components",
    tags=["components-admin"],
)
api_router.include_router(components.router, prefix="/components", tags=["components"])
# User-component override endpoints hang off /users/{user_id}/components/*.
api_router.include_router(components.users_router, prefix="/users", tags=["components"])
# Integrations: server-side OAuth code/refresh exchange. X-Service-Token auth.
api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
