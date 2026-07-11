"""Scrum Master agent: turns a one-line goal into a persisted roadmap.

One planner-tier model call returns a strict JSON roadmap — a flat, ordered list
of work items, each tagged with a milestone, kind, estimate, priority, and the
earlier items it depends on. The roadmap is validated (a malformed one gets a
single corrective round), then written to the durable `work_items` backlog with
its intra-roadmap dependencies resolved to real ids. With LLM_FAKE=1 a fixed
roadmap is returned so the path runs offline. Design note:
docs/architecture/PLANNING_SUITE.md.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.loop import parse_json_object
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole, Estimate, Priority, WorkItemKind
from engine.db.models import WorkItem
from engine.llm.router import model_router

MAX_ROADMAP_ITEMS = 20

_KINDS = frozenset(str(kind) for kind in WorkItemKind)
_ESTIMATES = frozenset(str(estimate) for estimate in Estimate)
_PRIORITIES = frozenset(str(priority) for priority in Priority)

ROADMAP_FORMAT = """Reply with only a JSON object, nothing around it:
{
  "items": [
    {
      "title": "<short imperative title>",
      "milestone": "<milestone name this item belongs to>",
      "kind": "feature" | "bug" | "chore" | "spike",
      "estimate": "small" | "medium" | "large",
      "priority": "low" | "medium" | "high" | "critical",
      "description": "<what to build and what done means>",
      "rationale": "<one sentence: why this size and priority>",
      "depends_on": [<1-based positions of earlier items this one needs>]
    }
  ]
}
List items in delivery order (earliest first). An item may only depend on items
listed before it."""


class RoadmapError(Exception):
    """The model's roadmap was missing or malformed; the message says why."""


_OFFLINE_ROADMAP: dict[str, Any] = {
    "items": [
        {
            "title": "Set up the foundations",
            "milestone": "Foundations",
            "kind": "chore",
            "estimate": "small",
            "priority": "high",
            "description": "Offline roadmap (LLM_FAKE=1): scaffolding for the goal.",
            "rationale": "Small because it is scaffolding; high because everything waits on it.",
            "depends_on": [],
        },
        {
            "title": "Build the core capability",
            "milestone": "Core",
            "kind": "feature",
            "estimate": "medium",
            "priority": "high",
            "description": "Offline stand-in for the main feature the goal asks for.",
            "rationale": "Medium because it is the main body of work the goal asks for.",
            "depends_on": [1],
        },
        {
            "title": "Add tests and documentation",
            "milestone": "Hardening",
            "kind": "chore",
            "estimate": "small",
            "priority": "medium",
            "description": "Offline stand-in for the polish pass.",
            "rationale": "Small because it only hardens what the core item already built.",
            "depends_on": [2],
        },
    ]
}


async def generate_roadmap(goal: str, repo_context: str = "", memory: str = "") -> dict[str, Any]:
    """A validated roadmap for the goal. Offline mode returns a fixed roadmap."""
    if get_settings().llm_fake:
        return validate_roadmap(_OFFLINE_ROADMAP)

    spec = get_agent_spec(AgentRole.SCRUM_MASTER)
    context = f"\n\nRepository context (existing files):\n{repo_context}" if repo_context else ""
    # Recalled team memory rides along as context, never as command
    # (docs/architecture/KNOWLEDGE_AND_MEMORY.md).
    memory_block = f"\n\n{memory}" if memory else ""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": f"Goal:\n{goal}{context}{memory_block}\n\n{ROADMAP_FORMAT}"},
    ]
    reply = await model_router.complete("planner", messages)
    try:
        return validate_roadmap(_parse(reply))
    except RoadmapError as exc:
        # One corrective round: show the model its mistake and ask again.
        messages.append(
            {"role": "user", "content": f"That roadmap was rejected: {exc}\n\n{ROADMAP_FORMAT}"}
        )
        reply = await model_router.complete("planner", messages)
        return validate_roadmap(_parse(reply))


def _parse(reply: str) -> dict[str, Any]:
    try:
        return parse_json_object(reply)
    except ValueError as exc:
        raise RoadmapError(f"roadmap {exc}") from exc


def _one_of(value: Any, allowed: frozenset[str], default: str | None) -> str | None:
    """Coerce an enum-ish field: keep it if valid, else fall back to a default
    rather than rejecting an otherwise-good roadmap over one stray label."""
    return value if isinstance(value, str) and value in allowed else default


def validate_roadmap(roadmap: dict[str, Any]) -> dict[str, Any]:
    items = roadmap.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ROADMAP_ITEMS:
        raise RoadmapError(f"roadmap needs between 1 and {MAX_ROADMAP_ITEMS} items")

    clean: list[dict[str, Any]] = []
    for sequence, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise RoadmapError(f"item {sequence} must be an object")
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            raise RoadmapError(f"item {sequence} needs a title")
        depends_on = item.get("depends_on") or []
        if not isinstance(depends_on, list) or any(
            not isinstance(dep, int) or not 1 <= dep < sequence for dep in depends_on
        ):
            raise RoadmapError(f"item {sequence} dependencies must be positions of earlier items")
        milestone = item.get("milestone")
        clean.append(
            {
                "title": title.strip()[:256],
                "milestone": milestone.strip()[:128] if isinstance(milestone, str) else None,
                "kind": _one_of(item.get("kind"), _KINDS, str(WorkItemKind.FEATURE)),
                "estimate": _one_of(item.get("estimate"), _ESTIMATES, None),
                "priority": _one_of(item.get("priority"), _PRIORITIES, str(Priority.MEDIUM)),
                "description": str(item.get("description") or "").strip() or None,
                "rationale": str(item.get("rationale") or "").strip() or None,
                "depends_on": depends_on,
            }
        )
    return {"items": clean}


async def persist_roadmap(
    db: AsyncSession, repository_id: Any, roadmap: dict[str, Any]
) -> list[WorkItem]:
    """Write a validated roadmap to the backlog, resolving position-based
    dependencies to the ids of the newly created work items."""
    items = roadmap["items"]
    created: list[WorkItem] = []
    for position, item in enumerate(items):
        work_item = WorkItem(
            repository_id=repository_id,
            title=item["title"],
            description=item["description"],
            kind=item["kind"],
            estimate=item["estimate"],
            priority=item["priority"],
            milestone=item["milestone"],
            rationale=item["rationale"],
            position=position,
        )
        db.add(work_item)
        created.append(work_item)
    await db.flush()  # assign ids before wiring dependencies
    created_ids = [work_item.id for work_item in created]

    for work_item, item in zip(created, items, strict=True):
        work_item.depends_on = [str(created[dep - 1].id) for dep in item["depends_on"]]
    await db.commit()

    # Re-query ordered rather than reading the just-committed (expired) objects —
    # and only the items this roadmap created, not whatever the backlog already held.
    return list(
        (
            await db.execute(
                select(WorkItem)
                .where(WorkItem.id.in_(created_ids))
                .order_by(WorkItem.position, WorkItem.created_at)
            )
        )
        .scalars()
        .all()
    )
