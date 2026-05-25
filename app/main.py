"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.error_handlers import register_handlers
from app.core.logging import configure_logging, get_logger
from app.core.redis import get_redis
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("startup", env=settings.app_env, version="0.1.0")
    yield
    await engine.dispose()
    log.info("shutdown")


def create_app() -> FastAPI:
    # /docs + /openapi.json hand attackers a full map of every route,
    # payload, header, and error code. Auth still gates the endpoints, but
    # leaving the schema public costs us reconnaissance hardening for no
    # operational benefit. Hide in production; ops can flip the env var
    # `EXPOSE_OPENAPI=true` for a one-off (e.g. importing into Postman).
    expose_openapi = (not settings.is_production) or settings.expose_openapi
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.app_debug,
        lifespan=lifespan,
        docs_url="/docs"        if expose_openapi else None,
        openapi_url="/openapi.json" if expose_openapi else None,
        redoc_url=None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["meta"])
    async def ready() -> dict[str, str]:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await get_redis().ping()
        return {"status": "ready"}

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
