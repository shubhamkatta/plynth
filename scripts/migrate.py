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
]


async def _run(db: AsyncSession, name: str, sql: str) -> None:
    log.info("applying %s", name)
    await db.execute(text(sql))


async def main() -> None:
    async with session_scope() as db:
        for name, sql in MIGRATIONS:
            await _run(db, name, sql)
    log.info("all migrations applied (%d)", len(MIGRATIONS))


if __name__ == "__main__":
    asyncio.run(main())
