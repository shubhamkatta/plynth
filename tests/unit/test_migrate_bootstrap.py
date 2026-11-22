"""The migrate runner's bootstrap path (T-026).

`scripts.migrate` only ever applied ALTER/CREATE INDEX statements, which assume
the tables already exist. On an empty database it failed, so standing up a new
environment needed a dump restored by hand — which is exactly what the AWS
cutover had to do.

The risky half of the fix is the *negative* case: bootstrap must never fire on
a database that already has a schema. If it did, `create_all` would run on
every deploy, and `_seed_fresh` would write rows on an environment that is
already live. The suite's own database is already migrated, so these tests
exercise that path directly.
"""

from __future__ import annotations

import pytest

from scripts import migrate


@pytest.mark.asyncio
async def test_does_not_bootstrap_a_database_that_already_has_a_schema() -> None:
    # The test session creates the schema, so this is the "existing env" path.
    assert await migrate._bootstrap_if_empty() is False


@pytest.mark.asyncio
async def test_bootstrap_detection_does_not_write_anything() -> None:
    """Calling the check twice must stay a read-only no-op — it runs on every
    single deploy, so a side effect here would compound."""
    assert await migrate._bootstrap_if_empty() is False
    assert await migrate._bootstrap_if_empty() is False


def test_sentinel_table_is_registered_in_the_metadata() -> None:
    """The emptiness probe is a hardcoded table name. If a rename ever left it
    pointing at a table that does not exist, every deploy would conclude the
    database is empty and re-run create_all + seed."""
    assert migrate._SENTINEL_TABLE in migrate.Base.metadata.tables


def test_every_migration_name_is_unique_and_ordered() -> None:
    """Names are the human record of what ran; duplicates would make a partial
    failure impossible to reason about."""
    names = [name for name, _ in migrate.MIGRATIONS]
    assert len(names) == len(set(names))
    assert names == sorted(names), "migrations must stay oldest-first"
