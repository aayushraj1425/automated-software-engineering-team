"""Routing semantics of the supervisor graph — injected executors, no LLM."""

from engine.agents.supervisor import (
    MAX_RETRIES,
    SupervisorState,
    TaskState,
    build_supervisor_graph,
)
from engine.db.enums import TaskStatus


def _task(task_id: str, sequence: int, depends_on: tuple[str, ...] = ()) -> TaskState:
    return TaskState(
        id=task_id,
        sequence=sequence,
        role="backend",
        title=f"task {task_id}",
        description=None,
        status=TaskStatus.PENDING,
        depends_on=list(depends_on),
        attempts=0,
        result=None,
    )


def _state(tasks: list[TaskState]) -> SupervisorState:
    return SupervisorState(tasks=tasks, current_task_id=None, failure=None)


def _by_id(final: dict) -> dict[str, dict]:
    return {t["id"]: t for t in final["tasks"]}


async def test_diamond_dependencies_run_in_order():
    order: list[str] = []

    async def executor(task):
        order.append(task["id"])
        return f"did {task['id']}"

    graph = build_supervisor_graph(executor)
    final = await graph.ainvoke(
        _state(
            [
                _task("a", 1),
                _task("b", 2, depends_on=("a",)),
                _task("c", 3, depends_on=("a",)),
                _task("d", 4, depends_on=("b", "c")),
            ]
        )
    )

    assert order[0] == "a" and order[-1] == "d"
    assert set(order) == {"a", "b", "c", "d"}
    assert final["failure"] is None
    assert all(t["status"] == TaskStatus.DONE for t in final["tasks"])
    assert _by_id(final)["a"]["result"] == "did a"


async def test_lowest_sequence_runs_first_among_eligible():
    order: list[str] = []

    async def executor(task):
        order.append(task["id"])
        return "ok"

    graph = build_supervisor_graph(executor)
    await graph.ainvoke(_state([_task("late", 2), _task("early", 1)]))
    assert order == ["early", "late"]


async def test_failed_attempt_is_retried_until_success():
    calls = {"n": 0}

    async def flaky(task):
        calls["n"] += 1
        if calls["n"] <= MAX_RETRIES:
            raise RuntimeError("transient")
        return "finally"

    graph = build_supervisor_graph(flaky)
    final = await graph.ainvoke(_state([_task("a", 1)]))

    task = _by_id(final)["a"]
    assert task["status"] == TaskStatus.DONE
    assert task["attempts"] == MAX_RETRIES + 1
    assert final["failure"] is None


async def test_exhausted_retries_fail_the_run_and_skip_the_rest():
    async def broken(task):
        raise RuntimeError("boom")

    graph = build_supervisor_graph(broken)
    final = await graph.ainvoke(_state([_task("a", 1), _task("b", 2, depends_on=("a",))]))

    tasks = _by_id(final)
    assert tasks["a"]["status"] == TaskStatus.FAILED
    assert tasks["a"]["attempts"] == MAX_RETRIES + 1
    assert tasks["b"]["status"] == TaskStatus.SKIPPED
    assert final["failure"] is not None and "boom" in final["failure"]


async def test_dependency_deadlock_fails_the_run():
    async def executor(task):
        return "ok"

    graph = build_supervisor_graph(executor)
    final = await graph.ainvoke(_state([_task("a", 1, depends_on=("ghost",))]))

    assert final["failure"] is not None and "deadlock" in final["failure"]
    assert _by_id(final)["a"]["status"] == TaskStatus.SKIPPED
