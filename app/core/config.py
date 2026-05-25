from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_name: str = "product-platform"
    app_debug: bool = False
    app_log_level: str = "INFO"
    # In production /docs + /openapi.json are hidden by default — leaking
    # the schema is free reconnaissance for attackers. Flip to True for a
    # one-off (e.g. importing into Postman) and revert when done.
    expose_openapi: bool = False

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=list)

    # Security
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 60 * 15
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    password_min_length: int = 12

    # Google OAuth (optional). When unset, POST /auth/google returns 401
    # "Google login is not configured on this platform". Per-product
    # opt-in for auto-provisioning new users lives in
    # Product.settings.features.google_auto_provision.
    google_client_id:     str = ""
    google_client_secret: str = ""

    # DB
    database_url: PostgresDsn
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # Redis
    redis_url: RedisDsn

    # Billing
    billing_provider: Literal["stripe", "mock"] = "mock"
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""

    # Tenancy / billing lifecycle
    default_trial_days: int = 14
    grace_period_days: int = 7

    # Rate limit
    rate_limit_per_minute: int = 120

    # Platform admin (for /admin/products bootstrap). Generate with `openssl rand -hex 32`.
    platform_admin_token: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
