"""The caller's provider keys, carried to the ModelRouter by a context variable.

Set once at an entry point (a chat request, a run's planning or execution) and
read inside the router — nothing in between needs new parameters, and the
router stays the single litellm gateway (ADR-0006). A user with no keys rides
the empty default and the server's .env keys apply. Design note:
docs/architecture/PROVIDER_KEYS.md.
"""

from contextvars import ContextVar

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import ProviderKey
from engine.security.crypto import DecryptionError, decrypt

log = structlog.get_logger()

# The providers a user may bring a key for (litellm model-id prefixes).
ALLOWED_PROVIDERS = ("anthropic", "openai", "gemini")

provider_keys_var: ContextVar[dict[str, str] | None] = ContextVar("provider_keys", default=None)


async def load_provider_keys(
    db: AsyncSession, user_id: str, org_id: str | None = None
) -> dict[str, str]:
    """The caller's decrypted keys, provider → plaintext.

    Resolution order: the user's personal key outranks the active
    organization's shared key, which outranks the server's `.env` key
    (PROVIDER_KEYS.md). A key that no longer decrypts (rotated encryption
    key) is skipped with a warning, never fatal."""
    personal = and_(ProviderKey.user_id == user_id, ProviderKey.org_id.is_(None))
    visible = or_(personal, ProviderKey.org_id == org_id) if org_id else personal
    rows = (
        (
            await db.execute(
                # Org keys first, personal second — later dict writes win.
                select(ProviderKey).where(visible).order_by(ProviderKey.org_id.is_(None))
            )
        )
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
