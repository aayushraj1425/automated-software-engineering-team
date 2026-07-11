"""Blocker detection and the next-item recommendation: pure-function tests.

No database — plan_insights reads a list of in-memory work items. An item is
blocked while any dependency is not done; the recommendation is the unblocked,
highest-priority item that has not started, ties broken by board order. Design
note: docs/architecture/PLANNING_SUITE.md.
"""

import uuid

from engine.db.models import WorkItem
from engine.planning.insights import plan_insights


def _item(
    title: str,
    status: str = "proposed",
    priority: str = "medium",
    depends_on: list[str] | None = None,
    position: int = 0,
) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        title=title,
        status=status,
        priority=priority,
        depends_on=depends_on or [],
        position=position,
    )


def test_an_item_waiting_on_an_unfinished_dependency_is_blocked():
    base = _item("Reset token model", status="in_progress")
    dependent = _item("Reset email", depends_on=[str(base.id)], position=1)

    insights = plan_insights([base, dependent])

    assert [entry.title for entry in insights.blocked] == ["Reset email"]
    assert insights.blocked[0].waiting_on == [str(base.id)]


def test_a_done_dependency_unblocks_the_item():
    base = _item("Reset token model", status="done")
    dependent = _item("Reset email", depends_on=[str(base.id)], position=1)

    insights = plan_insights([base, dependent])

    assert insights.blocked == []
    assert insights.recommended_id == str(dependent.id)


def test_a_cancelled_dependency_still_blocks():
    # A cancelled dependency will never finish — the item needs replanning,
    # and staying on the blocked list is what surfaces that.
    base = _item("Reset token model", status="cancelled")
    dependent = _item("Reset email", depends_on=[str(base.id)], position=1)

    insights = plan_insights([base, dependent])

    assert [entry.title for entry in insights.blocked] == ["Reset email"]


def test_recommendation_prefers_priority_then_board_order():
    low_first = _item("Tidy the docs", priority="low", position=0)
    critical_later = _item("Fix the login outage", priority="critical", position=1)
    high_a = _item("Add rate limiting", priority="high", position=2)
    high_b = _item("Add audit logging", priority="high", position=3)

    insights = plan_insights([low_first, critical_later, high_a, high_b])
    assert insights.recommended_id == str(critical_later.id)

    # without the critical item, the earlier of the two highs wins
    insights = plan_insights([low_first, high_a, high_b])
    assert insights.recommended_id == str(high_a.id)


def test_started_and_settled_items_are_never_recommended():
    in_progress = _item("Being built", status="in_progress")
    done = _item("Shipped", status="done", position=1)
    cancelled = _item("Dropped", status="cancelled", position=2)

    insights = plan_insights([in_progress, done, cancelled])

    assert insights.recommended_id is None
    assert insights.blocked == []


def test_a_manually_blocked_item_clears_once_its_dependency_finishes():
    base = _item("Schema migration", status="done")
    flagged = _item("Backfill data", status="blocked", depends_on=[str(base.id)], position=1)

    insights = plan_insights([base, flagged])

    # its dependency is done, so it is startable again — and recommended
    assert insights.blocked == []
    assert insights.recommended_id == str(flagged.id)


def test_an_empty_backlog_has_nothing_to_say():
    insights = plan_insights([])
    assert insights.blocked == []
    assert insights.recommended_id is None
