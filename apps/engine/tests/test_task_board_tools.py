"""Task-board tools: agents add discovered work and skip unnecessary tasks.

Three seams: the tools writing agent_tasks (with their guardrails), the
supervisor merging an ExecutionOutcome's board changes, and the runner's
executor reporting what changed. Design note:
docs/architecture/TASK_BOARD_TOOLS.md.
"""

import subprocess
import uuid

import pytest
from sqlalchemy import select

from engine.agents.runner import _make_task_executor, _to_task_state
from engine.agents.supervisor import (
    ExecutionOutcome,
    SupervisorState,
    TaskState,
    build_supervisor_graph,
)
from engine.agents.tools import (
    MAX_BOARD_TASKS,
    ToolError,
    add_task,
    schemas_for,
    update_task_status,
)
from engine.db.enums import RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentTask, Repository
from engine.db.models import AgentRun as AgentRunModel
from engine.db.session import session_scope
from engine.workspace.manager import Workspace


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def ws(tmp_path) -> Workspace:
    """A workspace over a real mini git repo (local, no network)."""
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@test.local")
    (repo / "README.md").write_text("# Demo\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    return Workspace(run_id=uuid.uuid4(), path=repo, branch="asep/run-test", base_sha=base)


async def _seed_run(ws: Workspace, tasks: int = 1) -> list[AgentTask]:
    """An executing run for the workspace's run id, with N pending tasks."""
    async with session_scope() as db:
        repo = Repository(owner_id="board-test", url=f"local://{uuid.uuid4().hex[:8]}")
        db.add(repo)
        await db.flush()
        db.add(
            AgentRunModel(
                id=ws.run_id,
                user_id="board-test",
                repository_id=repo.id,
                request="test the board",
                status=RunStatus.EXECUTING,
            )
        )
        rows = [
            AgentTask(run_id=ws.run_id, sequence=n, role="backend", title=f"task {n}")
            for n in range(1, tasks + 1)
        ]
        db.add_all(rows)
        await db.commit()
        return rows


async def _events(run_id: uuid.UUID, type_: str) -> list[AgentEvent]:
    async with session_scope() as db:
        return list(
            (
                await db.execute(
                    select(AgentEvent).where(AgentEvent.run_id == run_id, AgentEvent.type == type_)
                )
            )
            .scalars()
            .all()
        )


# ── The tools themselves ─────────────────────────────────────────────────────


async def test_add_task_appends_a_pending_row_with_the_next_sequence(ws, prepared_db):
    await _seed_run(ws, tasks=2)
    out = await add_task(ws, title="add missing tests", role="frontend")
    assert out == "added task #3 (frontend): add missing tests"

    async with session_scope() as db:
        row = (
            await db.execute(
                select(AgentTask).where(AgentTask.run_id == ws.run_id, AgentTask.sequence == 3)
            )
        ).scalar_one()
    assert row.status == TaskStatus.PENDING
    assert row.role == "frontend"
    assert row.depends_on == []

    created = await _events(ws.run_id, "task.created")
    assert len(created) == 1
    assert created[0].payload["title"] == "add missing tests"


async def test_add_task_guardrails(ws, prepared_db):
    await _seed_run(ws)
    with pytest.raises(ToolError, match="cannot take tasks"):
        await add_task(ws, title="review it all", role="reviewer")
    with pytest.raises(ToolError, match="title is empty"):
        await add_task(ws, title="   ")


async def test_add_task_refuses_a_full_board(ws, prepared_db):
    await _seed_run(ws, tasks=MAX_BOARD_TASKS)
    with pytest.raises(ToolError, match="cap"):
        await add_task(ws, title="one more")


async def test_update_task_status_skips_a_pending_task(ws, prepared_db):
    rows = await _seed_run(ws, tasks=2)
    out = await update_task_status(ws, sequence=2, status="skipped", reason="already implemented")
    assert out == "skipped task #2: task 2"

    async with session_scope() as db:
        row = await db.get(AgentTask, rows[1].id)
        assert row is not None
        assert row.status == TaskStatus.SKIPPED
        assert row.result == "already implemented"

    changed = await _events(ws.run_id, "task.status_changed")
    assert changed[-1].payload["reason"] == "already implemented"


async def test_update_task_status_guardrails(ws, prepared_db):
    rows = await _seed_run(ws, tasks=2)
    with pytest.raises(ToolError, match="only set status 'skipped'"):
        await update_task_status(ws, sequence=2, status="done")
    with pytest.raises(ToolError, match="no task #9"):
        await update_task_status(ws, sequence=9, status="skipped")

    async with session_scope() as db:
        row = await db.get(AgentTask, rows[0].id)
        assert row is not None
        row.status = TaskStatus.IN_PROGRESS
        await db.commit()
    with pytest.raises(ToolError, match="only pending tasks"):
        await update_task_status(ws, sequence=1, status="skipped")


async def test_skipping_a_dependency_of_unfinished_work_is_refused(ws, prepared_db):
    """A skipped dependency can never become done — its dependents would
    deadlock the board, so the tool refuses instead."""
    rows = await _seed_run(ws, tasks=2)
    async with session_scope() as db:
        dependent = await db.get(AgentTask, rows[1].id)
        assert dependent is not None
        dependent.depends_on = [str(rows[0].id)]
        await db.commit()

    with pytest.raises(ToolError, match="#2 still depend"):
        await update_task_status(ws, sequence=1, status="skipped")


def test_board_tools_have_schemas_for_the_model():
    names = [s["function"]["name"] for s in schemas_for(("add_task", "update_task_status"))]
    assert names == ["add_task", "update_task_status"]


# ── The supervisor merging board changes ────────────────────────────────────


def _task(task_id: str, sequence: int, status: str = TaskStatus.PENDING) -> TaskState:
    return TaskState(
        id=task_id,
        sequence=sequence,
        role="backend",
        title=f"task {task_id}",
        description=None,
        status=status,
        depends_on=[],
        attempts=0,
        result=None,
    )


async def test_supervisor_schedules_tasks_an_executor_reports(prepared_db):
    executed: list[str] = []

    async def executor(task):
        executed.append(task["id"])
        if task["id"] == "a":
            return ExecutionOutcome("did a", new_tasks=[_task("discovered", 2)])
        return f"did {task['id']}"

    graph = build_supervisor_graph(executor)
    final = await graph.ainvoke(
        SupervisorState(tasks=[_task("a", 1)], current_task_id=None, failure=None),
        {"recursion_limit": 50},
    )
    assert executed == ["a", "discovered"]
    assert final["failure"] is None
    assert {t["status"] for t in final["tasks"]} == {TaskStatus.DONE}


async def test_supervisor_honors_skips_an_executor_reports(prepared_db):
    executed: list[str] = []

    async def executor(task):
        executed.append(task["id"])
        return ExecutionOutcome(f"did {task['id']}", skipped_task_ids=["b"])

    graph = build_supervisor_graph(executor)
    final = await graph.ainvoke(
        SupervisorState(tasks=[_task("a", 1), _task("b", 2)], current_task_id=None, failure=None),
        {"recursion_limit": 50},
    )
    assert executed == ["a"]  # b was skipped mid-task and never ran
    by_id = {t["id"]: t for t in final["tasks"]}
    assert by_id["b"]["status"] == TaskStatus.SKIPPED
    assert final["failure"] is None


# ── The runner's executor reporting what changed ────────────────────────────


async def test_runner_executor_reports_new_and_skipped_tasks(ws, prepared_db):
    """The glue: after a task succeeds, the executor reloads the board and
    hands new rows and fresh skips back to the supervisor."""
    rows = await _seed_run(ws, tasks=2)
    board = [_to_task_state(r) for r in rows]
    known_ids = {t["id"] for t in board}
    execute = _make_task_executor(ws.run_id, "test the board", ws, known_ids)

    # Simulate the agents' mid-task tool use: one task added, one skipped.
    await add_task(ws, title="discovered follow-up", role="devops")
    await update_task_status(ws, sequence=2, status="skipped", reason="not needed")

    outcome = await execute(board[0])  # offline mode writes + commits a file
    assert isinstance(outcome, ExecutionOutcome)
    assert [t["title"] for t in outcome.new_tasks] == ["discovered follow-up"]
    assert str(rows[1].id) in outcome.skipped_task_ids
    # The next report must not repeat the same "new" task.
    assert all(t["id"] in known_ids for t in outcome.new_tasks)
