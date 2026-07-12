"""The connection store: which external services a user has linked.

One row per (user, kind); the secret config is AES-GCM ciphertext of a small
JSON blob, decrypted only here. The API activates kinds one adapter at a time,
so ACTIVE_KINDS is the allow-list a PUT is checked against. Design note:
docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.enums import IntegrationKind
from engine.db.models import IntegrationConnection
from engine.integrations import slack
from engine.security.crypto import DecryptionError, decrypt, encrypt

log = structlog.get_logger()

# The kinds whose adapter exists and the API will accept. Grows one at a time.
ACTIVE_KINDS: tuple[str, ...] = (IntegrationKind.SLACK,)


class ConfigError(ValueError):
    """The submitted config was missing or the wrong shape for its kind."""


def build_config(kind: str, raw: dict[str, Any]) -> tuple[str, str]:
    """Validate a submitted config for `kind` and return (json_config, label).

    The label is a non-secret hint safe to show on the settings page.
    """
    if kind == IntegrationKind.SLACK:
        url = str(raw.get("webhook_url", "")).strip()
        if not slack.is_webhook_url(url):
            raise ConfigError("A Slack webhook must be a https://hooks.slack.com/… URL")
        label = f"hooks.slack.com · ending {url[-4:]}"
        return json.dumps({"webhook_url": url}), label
    raise ConfigError(f"{kind} is not yet supported")


async def load_config(db: AsyncSession, user_id: str, kind: str) -> dict[str, Any] | None:
    """The decrypted config for a user's enabled connection of `kind`, or None.

    A config that no longer decrypts (rotated encryption key) is skipped with a
    warning, never fatal — the same rule as provider keys.
    """
    row = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.kind == kind,
                IntegrationConnection.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return json.loads(decrypt(row.encrypted_config))
    except (DecryptionError, ValueError):
        log.warning("integration.undecryptable", kind=kind, user_id=user_id)
        return None


def encrypt_config(json_config: str) -> str:
    return encrypt(json_config)
