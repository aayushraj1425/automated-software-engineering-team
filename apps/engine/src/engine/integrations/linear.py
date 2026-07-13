"""Linear adapter: create one issue through the GraphQL API.

A pure "create this there" function — it never touches the database or a work
item. In dry-run mode (INTEGRATIONS_DRY_RUN=1: tests, offline dev) it skips the
network and returns a deterministic placeholder, so the whole push path runs
without a real Linear workspace. Design note:
docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import httpx

from engine.config import get_settings
from engine.integrations.issues import IssueResult

GRAPHQL_URL = "https://api.linear.app/graphql"
_TIMEOUT_SECONDS = 15

_MUTATION = """
mutation IssueCreate($teamId: String!, $title: String!, $description: String) {
  issueCreate(input: {teamId: $teamId, title: $title, description: $description}) {
    success
    issue { identifier url }
  }
}
"""


class LinearError(Exception):
    """Linear rejected the request or could not be reached."""


async def create_issue(config: dict, title: str, description: str | None) -> IssueResult:
    """Create a Linear issue from a work item's title and description."""
    if get_settings().integrations_dry_run:
        return IssueResult(
            url="https://linear.app/dry-run/issue/DRY-1", identifier="DRY-1", dry_run=True
        )

    variables = {"teamId": config["team_id"], "title": title, "description": description or ""}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                GRAPHQL_URL,
                json={"query": _MUTATION, "variables": variables},
                headers={"Authorization": config["api_key"], "Content-Type": "application/json"},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise LinearError(f"could not reach Linear: {exc}") from exc

    if body.get("errors"):
        raise LinearError(f"Linear rejected the request: {body['errors']}")
    created = (body.get("data") or {}).get("issueCreate") or {}
    issue = created.get("issue")
    if not created.get("success") or not issue:
        raise LinearError("Linear did not create the issue")
    return IssueResult(url=issue["url"], identifier=issue["identifier"], dry_run=False)
