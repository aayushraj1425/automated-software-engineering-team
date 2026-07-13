"""Issue-tracker dispatch and the shared "an issue was created" contract.

`IssueResult` lives here — with the dispatcher, not any one adapter — so every
tracker returns the same thing. One dispatch entry per tracker kind, so the push
endpoint never names a specific tracker and a new tracker (Jira) slots in as one
more branch. Adapter-specific errors are translated into a common IssueError.
Design note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

from dataclasses import dataclass

from engine.db.enums import IntegrationKind


@dataclass(frozen=True)
class IssueResult:
    url: str
    identifier: str  # the tracker's human key, e.g. "ENG-42" or "PROJ-7"
    dry_run: bool


class IssueError(Exception):
    """An issue could not be created in the connected tracker."""


# The connection kinds that create issues (a subset of ACTIVE_KINDS).
ISSUE_TRACKER_KINDS: tuple[str, ...] = (IntegrationKind.LINEAR, IntegrationKind.JIRA)


async def create_issue(kind: str, config: dict, title: str, description: str | None) -> IssueResult:
    """Create an issue in `kind`'s tracker from a work item's title/description.

    The adapters are imported here (not at module top) so the dispatcher owns
    the shared IssueResult without a dispatcher↔adapter import cycle.
    """
    from engine.integrations import jira, linear

    try:
        if kind == IntegrationKind.LINEAR:
            return await linear.create_issue(config, title, description)
        if kind == IntegrationKind.JIRA:
            return await jira.create_issue(config, title, description)
    except (linear.LinearError, jira.JiraError) as exc:
        raise IssueError(str(exc)) from exc
    raise IssueError(f"{kind} is not a supported issue tracker")
