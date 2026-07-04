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
"""

from collections.abc import Awaitable, Callable
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


# Executes one task and returns its result summary; raises on failure.
TaskExecutor = Callable[[TaskState], Awaitable[str]]

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
        task["status"] = TaskStatus.DONE
        task["result"] = result
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
