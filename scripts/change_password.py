#!/usr/bin/env python3
"""Change a user's password on a deployed Plynth platform.

Run from your laptop (not the server). Stdlib only — no pip install.

Usage:
    python3 scripts/change_password.py

Defaults are baked for the first-deploy admin lockdown:
    BASE_URL     = http://localhost:8000
    PRODUCT_SLUG = platform
    EMAIL        = admin@example.com
    CURRENT_PW   = ChangeMeNow123!   (the seeded default)

Override any of them via env vars:
    EMAIL=alice@example.com \\
    BASE_URL=https://api.example.com \\
    PRODUCT_SLUG=chatbot \\
    CURRENT_PW='whatever' \\
    python3 scripts/change_password.py
"""

import getpass
import json
import os
import ssl
import sys
from urllib import error, request

BASE_URL     = os.environ.get("BASE_URL",     "http://localhost:8000")
PRODUCT_SLUG = os.environ.get("PRODUCT_SLUG", "platform")
EMAIL        = os.environ.get("EMAIL",        "admin@example.com")
CURRENT_PW   = os.environ.get("CURRENT_PW",   "ChangeMeNow123!")


def _ssl_ctx() -> ssl.SSLContext:
    """Use certifi's CA bundle if available (works around python.org Python
    on macOS shipping with an empty trust store). Falls back to whatever
    `ssl.create_default_context()` finds on the system."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_ctx()


def call(method: str, path: str, *, body: dict | None = None, token: str | None = None):
    headers = {
        "Content-Type":   "application/json",
        "X-Product-Slug": PRODUCT_SLUG,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(
        f"{BASE_URL}{path}",
        method=method,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with request.urlopen(req, context=_CTX) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw.decode(errors="replace")}


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print(f"Changing password for {EMAIL} on {BASE_URL}")
    new_pw  = getpass.getpass("New password (≥12 chars): ")
    new_pw2 = getpass.getpass("Confirm new password:     ")
    if new_pw != new_pw2:
        die("passwords don't match")
    if len(new_pw) < 12:
        die("password too short (min 12)")

    print("→ login as current user…")
    status, body = call("POST", "/api/v1/auth/login",
                        body={"email": EMAIL, "password": CURRENT_PW})
    if status != 200:
        die(f"login failed (HTTP {status}): {body}")
    token = body["access_token"]

    print("→ change password…")
    status, body = call("POST", "/api/v1/auth/password",
                        body={"current_password": CURRENT_PW, "new_password": new_pw},
                        token=token)
    if status != 204:
        die(f"change failed (HTTP {status}): {body}")

    print("→ verify new password works…")
    status, _ = call("POST", "/api/v1/auth/login",
                     body={"email": EMAIL, "password": new_pw})
    if status != 200:
        die(f"new password doesn't work (HTTP {status}) — something is wrong")

    print("→ verify old password is dead…")
    status, _ = call("POST", "/api/v1/auth/login",
                     body={"email": EMAIL, "password": CURRENT_PW})
    if status != 401:
        die(f"old password STILL works (HTTP {status}) — investigate immediately")

    print()
    print(f"✓ password changed successfully for {EMAIL}")
    print("  Save the new password in your password manager NOW.")


if __name__ == "__main__":
    main()
