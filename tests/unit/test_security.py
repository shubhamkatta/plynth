from uuid import uuid4

import jwt

from app.core.security import (
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)


def test_password_roundtrip() -> None:
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h)
    assert not verify_password("wrong-password-x", h)


def test_jwt_roundtrip() -> None:
    uid, tid, pid = uuid4(), uuid4(), uuid4()
    token, jti, exp = issue_token(subject=uid, tenant_id=tid, product_id=pid, typ="access")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(uid)
    assert payload["tid"] == str(tid)
    assert payload["pid"] == str(pid)
    assert payload["jti"] == jti


def test_jwt_type_mismatch_rejected() -> None:
    token, _, _ = issue_token(
        subject=uuid4(), tenant_id=None, product_id=uuid4(), typ="refresh"
    )
    try:
        decode_token(token, expected_type="access")
    except jwt.InvalidTokenError:
        return
    raise AssertionError("expected InvalidTokenError")


def test_rbac_wildcard_matching() -> None:
    from app.services.rbac import _matches

    assert _matches("*:*", "users:read")
    assert _matches("users:*", "users:read")
    assert _matches("users:read", "users:read")
    assert not _matches("users:read", "users:write")
    assert not _matches("billing:*", "users:read")
