"""Blocker detection and the next-item recommendation for a backlog.

Pure functions over a repository's work items — dependencies and statuses are
data, so no model call is involved and the answer is always the same for the
same backlog. An item is blocked while any dependency is not done (a cancelled
dependency blocks too: the item needs replanning, and flagging it surfaces
that). The recommendation is the next unblocked, highest-priority item that has
not been started, ties broken by board position. Design note:
docs/architecture/PLANNING_SUITE.md.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from engine.db.enums import Priority, WorkItemStatus
from engine.db.models import WorkItem

# Lower rank = more urgent; unknown labels sort with medium.
_PRIORITY_RANK: dict[str, int] = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}

_SETTLED = frozenset({WorkItemStatus.DONE, WorkItemStatus.CANCELLED})
_STARTABLE = frozenset({WorkItemStatus.PROPOSED, WorkItemStatus.READY, WorkItemStatus.BLOCKED})


@dataclass(frozen=True)
class BlockedItem:
    item_id: str
    title: str
    waiting_on: list[str]  # ids of the unfinished dependencies


@dataclass(frozen=True)
class PlanInsights:
    blocked: list[BlockedItem]
    recommended_id: str | None  # the next item to start, if any is unblocked


def plan_insights(items: Sequence[WorkItem]) -> PlanInsights:
    """Blocked items and the recommended next item for one repository's backlog.

    `items` is expected in board order (position, then created_at) — the order
    the list endpoint already returns — so ties fall to the item the user
    ranked higher.
    """
    by_id = {str(item.id): item for item in items}
    blocked: list[BlockedItem] = []
    candidates: list[WorkItem] = []

    for item in items:
        if item.status in _SETTLED:
            continue
        waiting_on = [
            dep
            for dep in item.depends_on
            if dep in by_id and by_id[dep].status != WorkItemStatus.DONE
        ]
        if waiting_on:
            blocked.append(
                BlockedItem(item_id=str(item.id), title=item.title, waiting_on=waiting_on)
            )
        elif item.status in _STARTABLE:
            # Unblocked and not yet started — a manual "blocked" status clears
            # once its dependencies finish, so it is startable again here.
            candidates.append(item)

    default_rank = _PRIORITY_RANK[Priority.MEDIUM]
    candidates.sort(key=lambda item: _PRIORITY_RANK.get(item.priority, default_rank))
    recommended = candidates[0] if candidates else None
    return PlanInsights(
        blocked=blocked,
        recommended_id=str(recommended.id) if recommended is not None else None,
    )
