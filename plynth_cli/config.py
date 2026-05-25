"""Per-user XDG config for plynth_cli.

Persists base URL, current session (access/refresh JWTs, product slug),
optional platform-admin token, and an optional acting-tenant slug. Stored
at ``$XDG_CONFIG_HOME/plynth/config.json`` (default
``~/.config/plynth/config.json``), permissions ``0600``.

This file is intentionally simple JSON — the CLI is single-user, so no
keyring dependency. If you want OS keyring storage, port the
``apps/admin-electron/src/main/api/secrets.ts`` keytar helpers.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".config"


def config_path() -> Path:
    return _xdg_config_home() / "plynth" / "config.json"


def _empty() -> dict[str, Any]:
    return {
        "base_url": DEFAULT_BASE_URL,
        "session": None,           # {access_token, refresh_token, expires_at, product_slug, email}
        "admin_token": None,       # platform-admin token (X-Platform-Admin-Token)
        "admin_product_slug": None,  # default product when calling under admin god-mode
        "acting_tenant_slug": None,
    }


def load_config() -> dict[str, Any]:
    """Read config from disk; return a fresh empty dict if missing/corrupt."""
    path = config_path()
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    merged = _empty()
    merged.update({k: v for k, v in data.items() if k in merged})
    return merged


def save_config(cfg: dict[str, Any]) -> None:
    """Atomically write config + chmod 600. Creates parent dir if missing."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        # Best-effort on non-POSIX filesystems.
        pass
    os.replace(tmp, path)


def clear_session() -> None:
    cfg = load_config()
    cfg["session"] = None
    save_config(cfg)


def clear_admin_token() -> None:
    cfg = load_config()
    cfg["admin_token"] = None
    cfg["admin_product_slug"] = None
    save_config(cfg)
