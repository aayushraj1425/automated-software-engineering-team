"""Supervisor graph: routes approved tasks to specialists by dependency order.

Deterministic routing over the task board — no LLM calls live here. The graph
is compiled around an injected task executor, so routing is testable without
agents and the Specialist Agents workstream plugs real executors in later.

Semantics (docs/architecture/AGENT_RUNTIME.md):
- a task is eligible when it is pending and every dependency is done;
  among eligible tasks the lowest sequence runs first
- a failed attempt returns the task to pending; after MAX_RETRIES retries
  the task fails and the run fails with a surfaced reason
- when the run fails (or dependencies deadlock), remaining unstarted tasks
  are marked skipped
- an executor may report board changes the agents made mid-task
  (TASK_BOARD_TOOLS.md): new tasks join the board and get scheduled like
  any other; skips flip in-memory pending tasks so they never execute
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypedDict, cast

from langgraph.graph import END, StateGraph

from engine.db.enums import TaskStatus

MAX_RETRIES = 2  # a task may be retried at most twice → three attempts total


class TaskState(TypedDict):
    id: str
    sequence: int
    role: str
    title: str
    description: str | None
    status: str
    depends_on: list[str]
    attempts: int
    result: str | None


class SupervisorState(TypedDict):
    tasks: list[TaskState]
    current_task_id: str | None
    failure: str | None


@dataclass
class ExecutionOutcome:
    """A task's result plus the board changes the agents made while working
    (through the task-board tools — TASK_BOARD_TOOLS.md). A plain string
    result means "no board changes"."""

    result: str
    new_tasks: list[TaskState] = field(default_factory=list)
    skipped_task_ids: list[str] = field(default_factory=list)


# Executes one task; raises on failure. Returning a plain string is
# shorthand for an ExecutionOutcome without board changes.
TaskExecutor = Callable[[TaskState], Awaitable[str | ExecutionOutcome]]

_FINISHED = (TaskStatus.DONE, TaskStatus.SKIPPED)


def eligible_tasks(tasks: list[TaskState]) -> list[TaskState]:
    done = {t["id"] for t in tasks if t["status"] == TaskStatus.DONE}
    return [t for t in tasks if t["status"] == TaskStatus.PENDING and set(t["depends_on"]) <= done]


def _schedule(state: SupervisorState) -> dict:
    if state.get("failure"):
        return {"current_task_id": None}
    tasks = state["tasks"]
    eligible = eligible_tasks(tasks)
    if eligible:
        nxt = min(eligible, key=lambda t: t["sequence"])
        return {"current_task_id": nxt["id"]}
    if all(t["status"] in _FINISHED for t in tasks):
        return {"current_task_id": None}
    stuck = sorted(t["sequence"] for t in tasks if t["status"] == TaskStatus.PENDING)
    return {
        "current_task_id": None,
        "failure": f"dependency deadlock: tasks {stuck} can never become eligible",
    }


def _after_schedule(state: SupervisorState) -> str:
    if state["current_task_id"] is not None:
        return "execute"
    if state.get("failure"):
        return "finalize"
    return END


def _finalize(state: SupervisorState) -> dict:
    tasks = [cast(TaskState, dict(t)) for t in state["tasks"]]
    for task in tasks:
        if task["status"] == TaskStatus.PENDING:
            task["status"] = TaskStatus.SKIPPED
    return {"tasks": tasks}


def _make_execute(executor: TaskExecutor):
    async def _execute(state: SupervisorState) -> dict:
        tasks = [cast(TaskState, dict(t)) for t in state["tasks"]]
        task = next(t for t in tasks if t["id"] == state["current_task_id"])
        task["status"] = TaskStatus.IN_PROGRESS
        task["attempts"] += 1
        try:
            result = await executor(task)
        except Exception as exc:
            if task["attempts"] > MAX_RETRIES:
                task["status"] = TaskStatus.FAILED
                return {
                    "tasks": tasks,
                    "failure": (
                        f"task {task['sequence']} ({task['title']}) failed after "
                        f"{task['attempts']} attempts: {exc}"
                    ),
                }
            task["status"] = TaskStatus.PENDING
            return {"tasks": tasks}
        outcome = result if isinstance(result, ExecutionOutcome) else ExecutionOutcome(result)
        task["status"] = TaskStatus.DONE
        task["result"] = outcome.result
        # Merge the board changes agents made mid-task: new tasks join the
        # board (and get scheduled), skips make sure a task an agent deemed
        # unnecessary never executes.
        known = {t["id"] for t in tasks}
        tasks.extend(t for t in outcome.new_tasks if t["id"] not in known)
        skipped = set(outcome.skipped_task_ids)
        for t in tasks:
            if t["id"] in skipped and t["status"] == TaskStatus.PENDING:
                t["status"] = TaskStatus.SKIPPED
        return {"tasks": tasks}

    return _execute


def build_supervisor_graph(executor: TaskExecutor):
    graph = StateGraph(SupervisorState)
    graph.add_node("schedule", _schedule)
    graph.add_node("execute", _make_execute(executor))
    graph.add_node("finalize", _finalize)
    graph.set_entry_point("schedule")
    graph.add_conditional_edges(
        "schedule", _after_schedule, {"execute": "execute", "finalize": "finalize", END: END}
    )
    graph.add_edge("execute", "schedule")
    graph.add_edge("finalize", END)
    return graph.compile()
