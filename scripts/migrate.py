"""Lightweight schema migrations runner.

This project bootstraps its initial schema via `Base.metadata.create_all`
(see deploy runbook). Until full Alembic adoption, schema changes land
here as idempotent `ALTER TABLE` / `CREATE INDEX IF NOT EXISTS` statements
and are run on every deploy:

    docker compose exec api python -m scripts.migrate

Each migration must be **idempotent** — running it twice is a no-op.
List them oldest-first; rerunning the whole file is the deploy command.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_scope

log = logging.getLogger("migrate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# Each entry: (name, SQL). Add new migrations to the END of the list.
MIGRATIONS: list[tuple[str, str]] = [
    (
        "0001_tenants_expires_at",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;",
    ),
    # Replace the full-table unique constraints on (tenant_id, email) and
    # (product_id, slug) with partial unique indexes that ignore soft-
    # deleted rows. Without this, deleting a user/tenant blocks re-using
    # their email/slug — surfaced as the IntegrityError 409 envelope.
    (
        "0002_users_email_partial_unique",
        """
        ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_tenant_email;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_email_alive
          ON users (tenant_id, email) WHERE deleted_at IS NULL;
        """,
    ),
    (
        "0003_tenants_slug_partial_unique",
        """
        ALTER TABLE tenants DROP CONSTRAINT IF EXISTS uq_tenants_product_slug;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_product_slug_alive
          ON tenants (product_id, slug) WHERE deleted_at IS NULL;
        """,
    ),
    # Forgot-password tokens. SHA-256 of the raw token, FK to user with
    # cascade delete. We never store the plaintext.
    (
        "0004_password_reset_tokens",
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
          id            UUID PRIMARY KEY,
          product_id    UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          user_id       UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
          token_hash    VARCHAR(64)  NOT NULL,
          expires_at    TIMESTAMPTZ  NOT NULL,
          used_at       TIMESTAMPTZ,
          requested_ip  VARCHAR(64),
          created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_password_reset_token_hash
          ON password_reset_tokens (token_hash);
        CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user_id
          ON password_reset_tokens (user_id);
        CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_product_id
          ON password_reset_tokens (product_id);
        """,
    ),
    # Jobs API (per docs/architecture.md § 6.2). Idempotency is a partial
    # unique index scoped to (product_id, tenant_id, type, idempotency_key).
    (
        "0005_jobs",
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id                    UUID PRIMARY KEY,
          product_id            UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          tenant_id             UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
          type                  VARCHAR(64)  NOT NULL,
          status                VARCHAR(32)  NOT NULL DEFAULT 'queued',
          payload               JSONB        NOT NULL DEFAULT '{}'::jsonb,
          result                JSONB,
          error                 JSONB,
          progress              INTEGER      NOT NULL DEFAULT 0,
          idempotency_key       VARCHAR(128),
          reference             VARCHAR(128),
          callback_url          VARCHAR(512),
          credits_charged       NUMERIC(18,4),
          queued_at             TIMESTAMPTZ  NOT NULL,
          started_at            TIMESTAMPTZ,
          completed_at          TIMESTAMPTZ,
          expires_at            TIMESTAMPTZ  NOT NULL,
          created_by_user_id    UUID         REFERENCES users(id)   ON DELETE SET NULL,
          acting_from_tenant_id UUID         REFERENCES tenants(id) ON DELETE SET NULL,
          created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_jobs_product_id              ON jobs (product_id);
        CREATE INDEX IF NOT EXISTS ix_jobs_tenant_id               ON jobs (tenant_id);
        CREATE INDEX IF NOT EXISTS ix_jobs_type                    ON jobs (type);
        CREATE INDEX IF NOT EXISTS ix_jobs_reference               ON jobs (reference);
        CREATE INDEX IF NOT EXISTS ix_jobs_created_by_user_id      ON jobs (created_by_user_id);
        CREATE INDEX IF NOT EXISTS ix_jobs_product_tenant_status   ON jobs (product_id, tenant_id, status);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_idempotency
          ON jobs (product_id, tenant_id, type, idempotency_key)
          WHERE idempotency_key IS NOT NULL
        """,
    ),
    # Storage API (per docs/architecture.md § 6.3). Per-tenant key/value
    # document store with collections, optimistic concurrency (version),
    # optional TTL, and a (collection, updated_at) sync-since index.
    (
        "0006_storage",
        """
        CREATE TABLE IF NOT EXISTS storage_collections (
          id                  UUID PRIMARY KEY,
          product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          tenant_id           UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
          name                VARCHAR(64)  NOT NULL,
          default_ttl_seconds INTEGER      NOT NULL DEFAULT 0,
          description         VARCHAR(255),
          settings            JSONB        NOT NULL DEFAULT '{}'::jsonb,
          created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_storage_collections_product_id ON storage_collections (product_id);
        CREATE INDEX IF NOT EXISTS ix_storage_collections_tenant_id  ON storage_collections (tenant_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_collections_name
          ON storage_collections (product_id, tenant_id, name);

        CREATE TABLE IF NOT EXISTS storage_documents (
          id            UUID PRIMARY KEY,
          product_id    UUID NOT NULL REFERENCES products(id)            ON DELETE CASCADE,
          tenant_id     UUID NOT NULL REFERENCES tenants(id)             ON DELETE CASCADE,
          collection_id UUID NOT NULL REFERENCES storage_collections(id) ON DELETE CASCADE,
          key           VARCHAR(255) NOT NULL,
          value         JSONB        NOT NULL DEFAULT '{}'::jsonb,
          version       INTEGER      NOT NULL DEFAULT 1,
          expires_at    TIMESTAMPTZ,
          created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_storage_documents_product_id    ON storage_documents (product_id);
        CREATE INDEX IF NOT EXISTS ix_storage_documents_tenant_id     ON storage_documents (tenant_id);
        CREATE INDEX IF NOT EXISTS ix_storage_documents_collection_id ON storage_documents (collection_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_documents_key
          ON storage_documents (product_id, tenant_id, collection_id, key);
        CREATE INDEX IF NOT EXISTS ix_storage_documents_sync
          ON storage_documents (product_id, tenant_id, collection_id, updated_at)
        """,
    ),
    # Outbound per-product webhooks. Endpoint config + delivery history.
    # Secret stored as plaintext (required for HMAC re-signing on dispatch);
    # never exposed via list/get responses — only once on create.
    (
        "0007_webhooks",
        """
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
          id          UUID PRIMARY KEY,
          product_id  UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          url         VARCHAR(2048) NOT NULL,
          description VARCHAR(255),
          secret      VARCHAR(64) NOT NULL,
          events      JSONB NOT NULL DEFAULT '[]'::jsonb,
          is_active   BOOLEAN NOT NULL DEFAULT TRUE,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_webhook_endpoints_product_id
          ON webhook_endpoints (product_id);

        CREATE TABLE IF NOT EXISTS webhook_deliveries (
          id              UUID PRIMARY KEY,
          endpoint_id     UUID NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
          product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          event_type      VARCHAR(64) NOT NULL,
          payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
          request_id      VARCHAR(64),
          attempt         INTEGER NOT NULL DEFAULT 0,
          status          VARCHAR(16) NOT NULL DEFAULT 'pending',
          response_status INTEGER,
          response_body   TEXT,
          delivered_at    TIMESTAMPTZ,
          next_retry_at   TIMESTAMPTZ,
          created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_product_created
          ON webhook_deliveries (product_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_endpoint_id
          ON webhook_deliveries (endpoint_id)
        """,
    ),
    # Per-product environment-variables vault + service tokens.
    # See app/services/env_var.py and app/services/service_token.py.
    # value_encrypted is BYTEA: nonce(12 bytes) || AES-GCM(ciphertext+tag)
    # with AAD = product_id || key. is_secret=false rows store utf-8
    # plaintext bytes (no encryption) for public-safe config.
    (
        "0008_env_vars_and_service_tokens",
        """
        CREATE TABLE IF NOT EXISTS product_env_vars (
          id              UUID PRIMARY KEY,
          product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          key             VARCHAR(128) NOT NULL,
          value_encrypted BYTEA NOT NULL,
          is_secret       BOOLEAN NOT NULL DEFAULT TRUE,
          description     VARCHAR(255),
          last_rotated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_product_env_vars_product_id
          ON product_env_vars (product_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_product_env_vars_key
          ON product_env_vars (product_id, key);

        CREATE TABLE IF NOT EXISTS product_service_tokens (
          id            UUID PRIMARY KEY,
          product_id    UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          name          VARCHAR(128) NOT NULL,
          token_hash    VARCHAR(64) NOT NULL,
          scopes        JSONB NOT NULL DEFAULT '["env:read"]'::jsonb,
          expires_at    TIMESTAMPTZ,
          revoked_at    TIMESTAMPTZ,
          last_used_at  TIMESTAMPTZ,
          last_used_ip  VARCHAR(64),
          created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_product_service_tokens_product_id
          ON product_service_tokens (product_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_service_tokens_token_hash
          ON product_service_tokens (token_hash)
        """,
    ),
    # Per-product components catalog + per-user enable/disable overrides.
    # Effective access for (user, component):
    #   override row → override.is_enabled
    #   no override row → component.is_default_enabled
    # Component delete cascades to override rows (FK).
    (
        "0009_product_components",
        """
        CREATE TABLE IF NOT EXISTS product_components (
          id                 UUID PRIMARY KEY,
          product_id         UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          code               VARCHAR(64)  NOT NULL,
          name               VARCHAR(128) NOT NULL,
          description        VARCHAR(255),
          is_default_enabled BOOLEAN NOT NULL DEFAULT TRUE,
          is_active          BOOLEAN NOT NULL DEFAULT TRUE,
          settings           JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_product_components_product_id
          ON product_components (product_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_product_components_product_code
          ON product_components (product_id, code);

        CREATE TABLE IF NOT EXISTS user_component_overrides (
          id              UUID PRIMARY KEY,
          product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          tenant_id       UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
          user_id         UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
          component_id    UUID NOT NULL REFERENCES product_components(id) ON DELETE CASCADE,
          is_enabled      BOOLEAN NOT NULL,
          reason          VARCHAR(255),
          set_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
          set_at          TIMESTAMPTZ NOT NULL,
          created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_user_component_overrides_product_id
          ON user_component_overrides (product_id);
        CREATE INDEX IF NOT EXISTS ix_user_component_overrides_tenant_id
          ON user_component_overrides (tenant_id);
        CREATE INDEX IF NOT EXISTS ix_user_component_overrides_user_id
          ON user_component_overrides (user_id);
        CREATE INDEX IF NOT EXISTS ix_user_component_overrides_component_id
          ON user_component_overrides (component_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_user_component_overrides_user_component
          ON user_component_overrides (user_id, component_id)
        """,
    ),
    # Plan-driven gating for components. NULL = no plan restriction.
    # A non-empty JSONB list of plan codes means "only tenants on one of
    # these plans get this component" (subject to per-user override).
    # See ARCHITECTURE.md § 6.5.
    (
        "0010_components_required_plan_codes",
        """
        ALTER TABLE product_components
          ADD COLUMN IF NOT EXISTS required_plan_codes JSONB
        """,
    ),
]


async def _run(db: AsyncSession, name: str, sql: str) -> None:
    log.info("applying %s", name)
    # asyncpg's text() doesn't run multiple statements per execute() — split
    # on `;` and run each non-empty statement. Migrations are idempotent
    # (DROP IF EXISTS / CREATE IF NOT EXISTS) so partial application on a
    # crash is safe to retry.
    for stmt in (s.strip() for s in sql.split(";")):
        if stmt:
            await db.execute(text(stmt))


async def main() -> None:
    async with session_scope() as db:
        for name, sql in MIGRATIONS:
            await _run(db, name, sql)
    log.info("all migrations applied (%d)", len(MIGRATIONS))


if __name__ == "__main__":
    asyncio.run(main())
