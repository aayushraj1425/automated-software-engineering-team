"""The caller's provider keys, carried to the ModelRouter by a context variable.

Set once at an entry point (a chat request, a run's planning or execution) and
read inside the router — nothing in between needs new parameters, and the
router stays the single litellm gateway (ADR-0006). A user with no keys rides
the empty default and the server's .env keys apply. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

from contextvars import ContextVar

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import ProviderKey
from engine.security.crypto import DecryptionError, decrypt

log = structlog.get_logger()

# The providers a user may bring a key for (litellm model-id prefixes).
ALLOWED_PROVIDERS = ("anthropic", "openai", "gemini")

provider_keys_var: ContextVar[dict[str, str] | None] = ContextVar("provider_keys", default=None)


async def load_provider_keys(db: AsyncSession, user_id: str) -> dict[str, str]:
    """The user's decrypted keys, provider → plaintext. A key that no longer
    decrypts (rotated encryption key) is skipped with a warning, never fatal."""
    rows = (
        (await db.execute(select(ProviderKey).where(ProviderKey.user_id == user_id)))
        .scalars()
        .all()
    )
    keys: dict[str, str] = {}
    for row in rows:
        try:
            keys[row.provider] = decrypt(row.encrypted_key)
        except DecryptionError:
            log.warning("provider_key.undecryptable", provider=row.provider, user_id=user_id)
    return keys


def api_key_for_model(model: str) -> str | None:
    """The caller's key for this model's provider, or None for the .env key.
    litellm model ids are provider-prefixed: "anthropic/claude-...", so the
    prefix is the provider."""
    provider = model.split("/", 1)[0]
    return (provider_keys_var.get() or {}).get(provider)
