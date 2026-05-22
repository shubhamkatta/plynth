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
