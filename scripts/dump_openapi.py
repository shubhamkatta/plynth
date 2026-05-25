"""Dump the FastAPI OpenAPI schema to docs/openapi.json.

Runs the app factory in-process (no server, no DB connection — lifespan
isn't entered when we just call `app.openapi()`), and serialises the
schema deterministically (sorted keys, 2-space indent) so the committed
file diffs cleanly.

In production the app hides `/docs` + `/openapi.json` for recon hardening
(see `app/main.py`). We flip `APP_ENV=test` + `EXPOSE_OPENAPI=true` BEFORE
importing the app so the schema is built unconditionally.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Settings is constructed at import time — stub the required env vars
# BEFORE importing anything that pulls `app.core.config`.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("EXPOSE_OPENAPI", "true")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "openapi-dump-placeholder-secret")
os.environ.setdefault("PLATFORM_ADMIN_TOKEN", "openapi-dump-placeholder-token")

# Make `import app...` work when invoked from anywhere.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.main import app  # noqa: E402  (env must be set first)

OUT_PATH = REPO_ROOT / "docs" / "openapi.json"


def main() -> int:
    schema = app.openapi()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    size = OUT_PATH.stat().st_size
    paths = len(schema.get("paths", {}))
    print(f"wrote {OUT_PATH} ({size} bytes, {paths} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
