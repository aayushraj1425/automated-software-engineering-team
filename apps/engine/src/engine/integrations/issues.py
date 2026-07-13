"""Issue-tracker dispatch: push a work item to whichever tracker is connected.

One entry per tracker kind, so the push endpoint never names a specific tracker
and a new tracker (Jira) slots in as one more mapping. Adapter-specific errors
are translated into a common IssueError. Design note:
docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

from engine.db.enums import IntegrationKind
from engine.integrations import linear
from engine.integrations.linear import IssueResult

# The connection kinds that create issues (a subset of ACTIVE_KINDS).
ISSUE_TRACKER_KINDS: tuple[str, ...] = (IntegrationKind.LINEAR,)


class IssueError(Exception):
    """An issue could not be created in the connected tracker."""


async def create_issue(kind: str, config: dict, title: str, description: str | None) -> IssueResult:
    """Create an issue in `kind`'s tracker from a work item's title/description."""
    try:
        if kind == IntegrationKind.LINEAR:
            return await linear.create_issue(config, title, description)
    except linear.LinearError as exc:
        raise IssueError(str(exc)) from exc
    raise IssueError(f"{kind} is not a supported issue tracker")
