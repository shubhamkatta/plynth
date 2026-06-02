"""AES-256-GCM at-rest encryption for the per-product env-vars vault.

Why GCM
    - Authenticated encryption — tampering with ciphertext fails
      decryption rather than silently producing garbage.
    - Built into ``cryptography`` (already a transitive dep).

Why AAD = product_id || key
    - Binds each ciphertext to the (product_id, key) row it lives in.
    - An attacker with DB write access can't take the ciphertext for
      mayva.STRIPE_KEY and paste it into chatbot.STRIPE_KEY — decryption
      will fail because the AAD won't match.

Key provenance
    - ``LocalKeyProvider`` reads ``settings.env_encryption_key`` (32 bytes,
      url-safe-b64 encoded). Generate with:
        python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())"
    - The provider interface (``KeyProvider``) is the seam for swapping
      in AWS KMS / Vault later without touching call sites.

Format on disk
    - ``BYTEA``: ``<12-byte nonce><ciphertext + 16-byte GCM tag>``
    - No separators / framing — fixed-width nonce, the rest is ciphertext.
"""

from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.exceptions import AppError

NONCE_LEN = 12  # AES-GCM standard


class CryptoConfigError(AppError):
    """Raised when the encryption layer is misconfigured (missing key,
    wrong size). Mapped to 503 by the global handler — operators get a
    clear signal instead of a stack trace."""

    status_code = 503
    code = "crypto_not_configured"


class KeyProvider(Protocol):
    """Lookup interface for the master encryption key. One method so
    swapping in KMS later is a five-minute job — implement ``key()`` to
    fetch from KMS / Vault / Secrets Manager."""

    def key(self) -> bytes:
        ...


class LocalKeyProvider:
    """Reads the master key from ``settings.env_encryption_key``.

    Validated lazily: the first encrypt/decrypt call raises
    ``CryptoConfigError`` if the key is missing or the wrong size. We
    don't fail at import time so the rest of the platform boots even
    when this feature isn't configured yet.
    """

    def __init__(self, raw: str | None = None) -> None:
        self._raw = raw if raw is not None else settings.env_encryption_key

    def key(self) -> bytes:
        if not self._raw:
            raise CryptoConfigError("ENV_ENCRYPTION_KEY not configured")
        try:
            # urlsafe_b64decode accepts both padded and unpadded; we strip
            # padding when generating so add it back if missing.
            padded = self._raw + "=" * (-len(self._raw) % 4)
            decoded = base64.urlsafe_b64decode(padded)
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            raise CryptoConfigError("ENV_ENCRYPTION_KEY is not valid base64") from exc
        if len(decoded) != 32:
            raise CryptoConfigError(
                f"ENV_ENCRYPTION_KEY must decode to 32 bytes (got {len(decoded)})"
            )
        return decoded


_default_provider: KeyProvider = LocalKeyProvider()


def set_key_provider(provider: KeyProvider) -> None:
    """Test hook: swap the global provider (e.g., feed a deterministic key
    in unit tests). Production code never touches this."""
    global _default_provider
    _default_provider = provider


def encrypt(plaintext: str, *, aad: bytes) -> bytes:
    """Encrypt ``plaintext`` with the master key, binding ``aad``.

    Returns the on-disk encoding: ``nonce || ciphertext+tag``. Always 12
    bytes longer than the ``plaintext + 16`` GCM tag overhead.
    """
    key = _default_provider.key()
    nonce = os.urandom(NONCE_LEN)
    aes = AESGCM(key)
    sealed = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return nonce + sealed


def decrypt(blob: bytes, *, aad: bytes) -> str:
    """Decrypt the on-disk ``nonce||ciphertext`` blob, verifying ``aad``.

    Raises ``CryptoConfigError`` on the key path; raises ``ValueError``
    on a tampered ciphertext (so callers can map to 500 + an audit row
    flagged for review).
    """
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("ciphertext too short")
    key = _default_provider.key()
    nonce, body = blob[:NONCE_LEN], blob[NONCE_LEN:]
    aes = AESGCM(key)
    try:
        return aes.decrypt(nonce, body, aad).decode("utf-8")
    except InvalidTag as exc:
        raise ValueError("ciphertext authentication failed") from exc


def aad_for(*, product_id: str, key: str) -> bytes:
    """Standard AAD: ``<product_uuid>|<env_key>`` as UTF-8.

    Binds each ciphertext to its (product, key) row so an attacker with
    DB write access can't substitute ciphertexts between rows.
    """
    return f"{product_id}|{key}".encode("utf-8")


def mask_preview(plaintext: str) -> str:
    """Render a non-secret preview of a secret value for list responses.

    ``sk_live_aB12...3xYZ`` for length > 12, otherwise just ``••••``.
    Never exposes more than 4+4 chars from the plaintext.
    """
    if len(plaintext) <= 8:
        return "•" * min(len(plaintext), 8)
    return f"{plaintext[:4]}…{plaintext[-4:]}"
