"""Product Manager agent: turns a feature request into an approvable plan.

The PM explores the repository with read-only tools, then answers with one
JSON object (summary + role-assigned tasks). The plan is validated strictly —
a malformed plan gets one corrective round, then the run fails rather than
executing garbage. With LLM_FAKE=1 a fixed plan is returned so the whole
pipeline runs offline.
"""

from typing import Any

from engine.agents.loop import LlmUsage, ToolObserver, parse_json_object, run_tool_loop
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.workspace.manager import Workspace

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
      "depends_on": [<sequence numbers of earlier tasks this one needs, 1-based>]
    }
  ]
}"""


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


async def create_plan(
    request: str, ws: Workspace, usage: LlmUsage, on_tool: ToolObserver | None = None
) -> dict[str, Any]:
    if get_settings().llm_fake:
        return validate_plan(_OFFLINE_PLAN)

    spec = get_agent_spec(AgentRole.PRODUCT_MANAGER)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": f"Feature request:\n{request}\n\n{PLAN_FORMAT}"},
    ]
    reply = await run_tool_loop(spec, ws, messages, usage, on_tool)
    try:
        return validate_plan(parse_plan(reply))
    except PlanError as exc:
        # One corrective round: show the model its mistake and ask again.
        messages.append(
            {"role": "user", "content": f"That plan was rejected: {exc}\n\n{PLAN_FORMAT}"}
        )
        reply = await run_tool_loop(spec, ws, messages, usage, on_tool)
        return validate_plan(parse_plan(reply))


def parse_plan(reply: str) -> dict[str, Any]:
    try:
        return parse_json_object(reply)
    except ValueError as exc:
        raise PlanError(f"plan {exc}") from exc


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = plan.get("summary")
    tasks = plan.get("tasks")
    if not isinstance(summary, str) or not summary.strip():
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
        clean_tasks.append(
            {
                "title": title.strip()[:256],
                "role": role,
                "description": str(task.get("description") or "").strip(),
                "depends_on": depends_on,
            }
        )
    return {"summary": summary.strip(), "tasks": clean_tasks}
