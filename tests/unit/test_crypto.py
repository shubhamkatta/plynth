"""Unit tests for the AES-GCM crypto helpers used by the env-vars vault."""

from __future__ import annotations

import pytest

from app.core.crypto import (
    CryptoConfigError,
    LocalKeyProvider,
    aad_for,
    decrypt,
    encrypt,
    mask_preview,
    set_key_provider,
)


def test_roundtrip_basic() -> None:
    aad = aad_for(product_id="11111111-1111-1111-1111-111111111111", key="STRIPE")
    sealed = encrypt("sk_live_secret", aad=aad)
    assert decrypt(sealed, aad=aad) == "sk_live_secret"
    # Sealed != plaintext (defence against an obviously-broken cipher).
    assert b"sk_live_secret" not in sealed


def test_substitution_attack_rejected() -> None:
    """An attacker with DB write access cannot move a ciphertext between
    (product_id, key) rows — AAD binding rejects the swap."""
    aad_a = aad_for(product_id="11111111-1111-1111-1111-111111111111", key="STRIPE")
    aad_b = aad_for(product_id="22222222-2222-2222-2222-222222222222", key="STRIPE")
    sealed = encrypt("hunter2", aad=aad_a)
    with pytest.raises(ValueError, match="authentication failed"):
        decrypt(sealed, aad=aad_b)


def test_tamper_rejected() -> None:
    aad = aad_for(product_id="11111111-1111-1111-1111-111111111111", key="X")
    sealed = encrypt("hunter2", aad=aad)
    tampered = sealed[:-1] + bytes([sealed[-1] ^ 0xff])
    with pytest.raises(ValueError, match="authentication failed"):
        decrypt(tampered, aad=aad)


def test_unique_nonces() -> None:
    aad = aad_for(product_id="11111111-1111-1111-1111-111111111111", key="X")
    a = encrypt("same plaintext", aad=aad)
    b = encrypt("same plaintext", aad=aad)
    # Different nonces => different ciphertexts even for identical input.
    assert a != b


def test_too_short_ciphertext_raises() -> None:
    with pytest.raises(ValueError, match="too short"):
        decrypt(b"\x00" * 10, aad=b"x")


def test_mask_preview_shapes() -> None:
    assert mask_preview("short") == "•••••"
    assert mask_preview("sk_live_1234567890abcd") == "sk_l…abcd"
    assert mask_preview("12345678") == "••••••••"  # exactly 8 → no leak


def test_missing_key_raises_clear_error() -> None:
    set_key_provider(LocalKeyProvider(raw=""))
    try:
        with pytest.raises(CryptoConfigError):
            encrypt("x", aad=b"y")
    finally:
        # Restore the test-suite key for subsequent tests.
        set_key_provider(LocalKeyProvider())


def test_wrong_key_size_raises() -> None:
    # 16-byte key (b64-encoded) — would be valid AES-128 but we require 256.
    import base64
    short_key = base64.urlsafe_b64encode(b"\x00" * 16).rstrip(b"=").decode()
    set_key_provider(LocalKeyProvider(raw=short_key))
    try:
        with pytest.raises(CryptoConfigError, match="32 bytes"):
            encrypt("x", aad=b"y")
    finally:
        set_key_provider(LocalKeyProvider())
