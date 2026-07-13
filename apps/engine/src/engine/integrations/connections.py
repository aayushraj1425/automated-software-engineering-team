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
ACTIVE_KINDS: tuple[str, ...] = (
    IntegrationKind.SLACK,
    IntegrationKind.LINEAR,
    IntegrationKind.JIRA,
)


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
    if kind == IntegrationKind.LINEAR:
        api_key = str(raw.get("api_key", "")).strip()
        team_id = str(raw.get("team_id", "")).strip()
        if not api_key or not team_id:
            raise ConfigError("Linear needs both an API key and a team id")
        label = f"Linear · team …{team_id[-6:]}"
        return json.dumps({"api_key": api_key, "team_id": team_id}), label
    if kind == IntegrationKind.JIRA:
        base_url = str(raw.get("base_url", "")).strip().rstrip("/")
        email = str(raw.get("email", "")).strip()
        api_token = str(raw.get("api_token", "")).strip()
        project_key = str(raw.get("project_key", "")).strip()
        if not (base_url.startswith("https://") and email and api_token and project_key):
            raise ConfigError("Jira needs a https base URL, email, API token, and project key")
        host = base_url.split("://", 1)[1]
        label = f"Jira · {project_key} @ {host}"
        return (
            json.dumps(
                {
                    "base_url": base_url,
                    "email": email,
                    "api_token": api_token,
                    "project_key": project_key,
                }
            ),
            label,
        )
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
