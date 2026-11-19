"""Product Manager agent: turns a feature request into an approvable plan.

The PM explores the repository with read-only tools, then answers with one
JSON object (summary + role-assigned tasks). The plan is validated strictly —
a malformed plan gets one corrective round, then the run fails rather than
executing garbage. With LLM_FAKE=1 a fixed plan is returned so the whole
pipeline runs offline.
"""

from dataclasses import replace
from typing import Any

from engine.agents.loop import (
    LlmUsage,
    ReasoningObserver,
    ToolObserver,
    parse_json_object,
    run_tool_loop,
)
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.llm.catalog import SeatLevel
from engine.workspace.manager import Workspace

# Levels a task may ask for. Senior is for the hardest or cross-service work;
# Principal and Support seats never take tasks from the board.
TASK_LEVELS = frozenset({"engineer", "senior"})
ENGINEER_ROLES = frozenset(
    str(role) for role in (AgentRole.BACKEND, AgentRole.FRONTEND, AgentRole.DEVOPS)
)
MAX_PLAN_TASKS = 8

PLAN_FORMAT = """Reply with only a JSON object, nothing around it:
{
  "summary": "<mini-specification: the problem, intended behavior, acceptance criteria>",
  "tasks": [
    {
      "title": "<short imperative title>",
      "role": "backend" | "frontend" | "devops",
      "description": "<what to change, where, and what done means>",
      "level": "engineer" | "senior",
      "depends_on": [<sequence numbers of earlier tasks this one needs, 1-based>]
    }
  ]
}
Use level "engineer" for normal tasks. Use "senior" only for the hardest tasks or
changes that cross services. When unsure, use "engineer"."""


class PlanError(Exception):
    """The model's plan was missing or malformed; the message says why."""


_OFFLINE_PLAN: dict[str, Any] = {
    "summary": "Offline plan (LLM_FAKE=1): exercises the whole pipeline without a model.",
    "tasks": [
        {
            "title": "Implement the backend change",
            "role": "backend",
            "description": "Offline stand-in for the backend part of the request.",
            "depends_on": [],
        },
        {
            "title": "Implement the frontend change",
            "role": "frontend",
            "description": "Offline stand-in for the frontend part of the request.",
            "depends_on": [],
        },
        {
            "title": "Wire configuration and checks",
            "role": "devops",
            "description": "Offline stand-in for configuration and CI wiring.",
            "depends_on": [1, 2],
        },
    ],
}

# The Complex offline plan gives the hardest task to a Senior seat, so offline runs
# exercise task levels and the roster too.
_OFFLINE_COMPLEX_PLAN: dict[str, Any] = {
    **_OFFLINE_PLAN,
    "summary": "Offline Complex plan (LLM_FAKE=1): follows the Principal's design note.",
    "tasks": [
        {**task, "level": "senior"} if task["role"] == "devops" else task
        for task in _OFFLINE_PLAN["tasks"]
    ],
}


async def create_plan(
    request: str,
    ws: Workspace,
    usage: LlmUsage,
    on_tool: ToolObserver | None = None,
    memory: str = "",
    on_reasoning: ReasoningObserver | None = None,
    quick: bool = False,
    design_note: str = "",
    complex_run: bool = False,
) -> dict[str, Any]:
    if get_settings().llm_fake:
        if quick:
            return validate_plan(
                {
                    "summary": "Offline Quick plan: one engineer implements and tests the request.",
                    "tasks": [
                        {
                            "title": "Implement the small change",
                            "role": "backend",
                            "description": request,
                            "depends_on": [],
                        }
                    ],
                }
            )
        return validate_plan(_OFFLINE_COMPLEX_PLAN if complex_run else _OFFLINE_PLAN)

    spec = get_agent_spec(AgentRole.PRODUCT_MANAGER)
    if quick:
        # The same Engineer plans and implements, with read-only planning tools.
        spec = replace(spec, role=AgentRole.BACKEND, model_tier="coder", level=SeatLevel.ENGINEER)
    # Recalled team memory rides along as context, never as command
    # (docs/architecture/planning-knowledge/KNOWLEDGE_AND_MEMORY.md).
    memory_block = f"{memory}\n\n" if memory else ""
    if design_note:
        memory_block += (
            "The Principal Engineer's design note is binding context for this plan. "
            "Split the work along it and give hard or cross-service tasks level senior:\n"
            f"{design_note}\n\n"
        )
    if quick:
        memory_block += (
            "Prefer at most two tasks for a single backend engineer using the backend role. "
            "If more tasks or specialists are needed, return the complete plan "
            "so it can escalate.\n\n"
        )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": f"{memory_block}Feature request:\n{request}\n\n{PLAN_FORMAT}"},
    ]
    reply = await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)
    try:
        return validate_plan(parse_plan(reply), quick=quick)
    except PlanError as exc:
        # One corrective round: show the model its mistake and ask again.
        messages.append(
            {"role": "user", "content": f"That plan was rejected: {exc}\n\n{PLAN_FORMAT}"}
        )
        reply = await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)
        return validate_plan(parse_plan(reply), quick=quick)


def parse_plan(reply: str) -> dict[str, Any]:
    try:
        return parse_json_object(reply)
    except ValueError as exc:
        raise PlanError(f"plan {exc}") from exc


def _coerce_summary(summary: Any) -> str:
    """The contract asks for a string, but models often structure the summary
    as an object (problem / behavior / acceptance criteria). That is a fine
    summary — flatten it instead of rejecting the plan."""
    if isinstance(summary, str):
        return summary.strip()
    if isinstance(summary, dict):
        lines: list[str] = []
        for key, value in summary.items():
            if isinstance(value, list):
                value = "; ".join(str(item) for item in value)
            lines.append(f"{str(key).replace('_', ' ').capitalize()}: {value}")
        return "\n".join(lines).strip()
    return ""


def validate_plan(plan: dict[str, Any], quick: bool = False) -> dict[str, Any]:
    summary = _coerce_summary(plan.get("summary"))
    tasks = plan.get("tasks")
    if not summary:
        raise PlanError("plan needs a non-empty summary")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_PLAN_TASKS:
        raise PlanError(f"plan needs between 1 and {MAX_PLAN_TASKS} tasks")

    clean_tasks: list[dict[str, Any]] = []
    for sequence, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise PlanError(f"task {sequence} must be an object")
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            raise PlanError(f"task {sequence} needs a title")
        role = task.get("role")
        if role not in ENGINEER_ROLES:
            raise PlanError(
                f"task {sequence} has role {role!r}; allowed roles: {sorted(ENGINEER_ROLES)}"
            )
        depends_on = task.get("depends_on") or []
        if not isinstance(depends_on, list) or any(
            not isinstance(dep, int) or not 1 <= dep < sequence for dep in depends_on
        ):
            raise PlanError(
                f"task {sequence} dependencies must be sequence numbers of earlier tasks"
            )
        level = task.get("level") or "engineer"
        if level not in TASK_LEVELS:
            raise PlanError(f"task {sequence} has level {level!r}; allowed: {sorted(TASK_LEVELS)}")
        clean_tasks.append(
            {
                "title": title.strip()[:256],
                "role": role,
                # Quick work always runs on one regular Engineer.
                "level": "engineer" if quick else level,
                "description": str(task.get("description") or "").strip(),
                "depends_on": depends_on,
            }
        )
    return {"summary": summary, "tasks": clean_tasks}
