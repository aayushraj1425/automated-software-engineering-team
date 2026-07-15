"""Secret encryption at rest: AES-GCM for bring-your-own provider keys.

The database only ever holds ciphertext. The encryption key comes from
ENGINE_ENCRYPTION_KEY (base64, 32 bytes); when unset — development — it is
derived from ENGINE_SERVICE_SECRET so the dev loop needs no extra setup, and
production must set a dedicated value. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

import base64
import hashlib
import os

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from engine.config import get_settings

log = structlog.get_logger(__name__)

_NONCE_BYTES = 12  # the AES-GCM standard nonce size


class DecryptionError(Exception):
    """The ciphertext could not be decrypted (wrong key, or tampered data)."""


def _key() -> bytes:
    configured = get_settings().engine_encryption_key
    if configured:
        key = base64.urlsafe_b64decode(configured)
        if len(key) != 32:
            raise ValueError("ENGINE_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return key
    # Dev fallback: deterministic from the service secret, no extra setup.
    return hashlib.sha256(get_settings().engine_service_secret.encode()).digest()


def warn_if_derived_key() -> bool:
    """Loudly flag the dev key fallback at startup (security-audit finding 2).

    Deriving the encryption key from ENGINE_SERVICE_SECRET is right for the
    dev loop and wrong for production: one leaked secret would compromise
    both transport auth and every secret at rest. Returns True when it warned
    so callers (and the test) can see the check fired.
    """
    if get_settings().engine_encryption_key:
        return False
    log.warning(
        "crypto.derived_dev_key",
        detail=(
            "ENGINE_ENCRYPTION_KEY is not set — secrets at rest are encrypted "
            "with a key derived from ENGINE_SERVICE_SECRET. Set a dedicated "
            "32-byte base64 key in production (docs/security/SECURITY_AUDIT.md)."
        ),
    )
    return True


def encrypt(plaintext: str) -> str:
    """Encrypt to a base64 token (nonce + ciphertext, authenticated)."""
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt(token: str) -> str:
    """Decrypt a token from `encrypt`; raises DecryptionError on any failure."""
    try:
        raw = base64.urlsafe_b64decode(token)
        plaintext = AESGCM(_key()).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], None)
        return plaintext.decode()
    except Exception as exc:
        raise DecryptionError("could not decrypt the stored secret") from exc
