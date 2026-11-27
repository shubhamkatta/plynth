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
    billing_provider: Literal["stripe", "razorpay", "mock"] = "mock"
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    # Razorpay (India). key_id + key_secret authenticate REST calls (Basic auth);
    # webhook_secret verifies the X-Razorpay-Signature HMAC on inbound events.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Tenancy / billing lifecycle
    default_trial_days: int = 14
    grace_period_days: int = 7
    # Days past `trial_end` a TRIAL subscription may linger before the sweep
    # marks it EXPIRED. Absorbs the delay between Razorpay's first charge at
    # `start_at` and its `subscription.charged` webhook reaching us.
    trial_expiry_buffer_days: int = 1

    # Invites
    invite_ttl_days: int = 7
    # Public origin of THIS API. Used to build the fallback hosted invite page
    # link (`<public_base_url>/invite?token=…`) for products without
    # `settings.app_url`.
    public_base_url: str = "https://api.example.com"

    # --- Outbound-email branding ---------------------------------------------
    # Every brand string in a transactional email comes from here, injected
    # once in `providers.notifications.render`. They are settings rather than
    # literals because this is a multi-product platform: the scaffold must not
    # ship one product's name, tagline or marketing copy in its templates, and
    # a deployment that does have a brand should not have to fork the template
    # module to say so.
    #
    # The defaults are deliberately plain, not placeholders-to-be-replaced: an
    # unconfigured deployment sends correct, unbranded transactional mail. Each
    # value can also be overridden per-send through the render context, which
    # is the hook a future per-product branding lookup uses.
    brand_name: str = "Acme"
    #: Appears after the product name in the footer ("Acme — <tagline>").
    #: Empty renders the name alone.
    brand_tagline: str = ""
    #: Why the recipient is getting this. Empty falls back to
    #: "You're getting this because you have an <brand_name> account."
    brand_footer_note: str = ""
    #: One sentence on what the product does, used in the invite. Empty omits
    #: the sentence rather than printing an empty paragraph.
    brand_pitch: str = ""
    #: The same idea in the second person, for the invite's "once you're in".
    brand_pitch_inside: str = ""
    #: A promise worth making up front (e.g. a consent or safety guarantee),
    #: shown in the welcome. Empty omits it.
    brand_promise: str = ""
    #: The welcome email's day-one steps, as a JSON array of strings. Each may
    #: contain simple inline HTML (`<strong>`). Empty uses a generic set.
    brand_welcome_steps: str = ""

    # --- Catalog seeding -----------------------------------------------------
    # `scripts/seed_acme.py` provisions a practice product's plan catalog,
    # component entitlements and credit grants. Which product it targets is
    # configuration rather than a literal, for the same reason the brand
    # strings above are: the scaffold ships one generic catalog, and a
    # deployment that runs it against a real product should not have to fork
    # the script to name it.
    #
    # Mind the blast radius: the seed CREATES the product when the slug is
    # missing, so a wrong value here provisions a second, parallel product
    # instead of updating the intended one. Any environment with a real
    # product should set this explicitly.
    seed_product_slug: str = "acme-practice"
    #: Display name, used ONLY when the seed creates the product.
    seed_product_name: str = "Acme Practice"

    # Transactional email. `log` (default) only logs; `ses` sends via Amazon
    # SES. Credentials resolve via the standard AWS chain (instance role / env)
    # unless AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY are set explicitly.
    email_provider: Literal["log", "ses"] = "log"
    email_from_address: str = ""
    # SES configuration set to attach to every send. Without one, SES has
    # nowhere to publish bounce/complaint events, so deliverability problems
    # are invisible — which is the gap AWS asks about when refusing production
    # access. Empty = omit the parameter entirely; naming a set that does not
    # exist makes SES reject the send, so this stays opt-in.
    ses_configuration_set: str = ""
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Rate limit
    rate_limit_per_minute: int = 120

    # Platform admin (for /admin/products bootstrap). Generate with `openssl rand -hex 32`.
    platform_admin_token: str = ""

    # Per-product env-vars vault (app.services.env_var). 32-byte key,
    # base64 (url-safe, no padding). Generate with:
    #   python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())"
    # If unset, the env-vars endpoints return 503 — the rest of the
    # platform keeps working. NEVER commit a real value; load from /etc
    # / .env / secret manager only.
    env_encryption_key: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
