"""Jira adapter: create one issue through the REST API (Jira Cloud v3).

A pure "create this there" function — it never touches the database or a work
item. Auth is HTTP Basic with an email + API token; the v3 API wants the
description as an Atlassian Document Format node. In dry-run mode
(INTEGRATIONS_DRY_RUN=1: tests, offline dev) it skips the network and returns a
deterministic placeholder, so the whole push path runs without a real Jira site.
Design note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import base64

import httpx

from engine.config import get_settings
from engine.integrations.issues import IssueResult

_TIMEOUT_SECONDS = 15
_ISSUE_TYPE = "Task"
_MAX_SUMMARY = 255


class JiraError(Exception):
    """Jira rejected the request or could not be reached."""


def _adf(text: str) -> dict:
    """Wrap plain text in a minimal Atlassian Document Format node (v3 API)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _browse_url(base_url: str, key: str) -> str:
    return f"{base_url}/browse/{key}"


async def create_issue(config: dict, title: str, description: str | None) -> IssueResult:
    """Create a Jira issue from a work item's title and description."""
    base_url = config["base_url"]
    if get_settings().integrations_dry_run:
        return IssueResult(url=_browse_url(base_url, "DRY-1"), identifier="DRY-1", dry_run=True)

    fields: dict = {
        "project": {"key": config["project_key"]},
        "summary": title[:_MAX_SUMMARY],
        "issuetype": {"name": _ISSUE_TYPE},
    }
    if description:
        fields["description"] = _adf(description)
    token = base64.b64encode(f"{config['email']}:{config['api_token']}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/rest/api/3/issue",
                json={"fields": fields},
                headers={
                    "Authorization": f"Basic {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise JiraError(f"could not reach Jira: {exc}") from exc

    key = body.get("key")
    if not key:
        raise JiraError(f"Jira did not return an issue key: {body}")
    return IssueResult(url=_browse_url(base_url, key), identifier=key, dry_run=False)
