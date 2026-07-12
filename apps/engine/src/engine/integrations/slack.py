"""Slack adapter: post one message to an incoming webhook.

A pure "send this there" function — it never touches the database or a run. In
dry-run mode (INTEGRATIONS_DRY_RUN=1: tests, offline dev) it skips the network
and reports success, so the whole notify path runs without a real workspace.
Design note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import httpx

from engine.config import get_settings

WEBHOOK_PREFIX = "https://hooks.slack.com/"
_TIMEOUT_SECONDS = 10


class SlackError(Exception):
    """Slack rejected the message or could not be reached."""


def is_webhook_url(url: str) -> bool:
    return url.startswith(WEBHOOK_PREFIX)


async def post_message(webhook_url: str, text: str) -> bool:
    """Post `text` to a Slack incoming webhook. Returns True when a message was
    actually sent, False when dry-run skipped the network. Raises SlackError on
    a real failure."""
    if get_settings().integrations_dry_run:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(webhook_url, json={"text": text})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SlackError(f"could not post to Slack: {exc}") from exc
    return True
