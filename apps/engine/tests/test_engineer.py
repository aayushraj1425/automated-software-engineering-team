"""Engineer agents in offline mode: real tools, real git, no model."""

import uuid

import pytest

from engine.agents.engineer import execute_task
from engine.agents.loop import LlmUsage
from engine.agents.supervisor import TaskState
from engine.config import get_settings
from engine.workspace.manager import create_scratch_workspace, run_git


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(root))
    return root


def _task(sequence: int = 1, role: str = "backend") -> TaskState:
    return TaskState(
        id=str(uuid.uuid4()),
        sequence=sequence,
        role=role,
        title="Implement the change",
        description="Offline test task",
        status="pending",
        depends_on=[],
        attempts=1,
        result=None,
    )


async def test_offline_engineer_writes_and_commits(workspace_root):
    ws = await create_scratch_workspace(uuid.uuid4())

    result = await execute_task(_task(), "Add a /status endpoint", ws, LlmUsage())

    assert ".asep/task-1.md" in result
    assert (ws.path / ".asep" / "task-1.md").is_file()
    log = await run_git(ws.path, "log", "--oneline")
    assert "task 1: Implement the change" in log
    diff = await run_git(ws.path, "diff", ws.base_sha, "--name-only")
    assert diff.strip() == ".asep/task-1.md"


async def test_scratch_workspace_starts_on_the_run_branch(workspace_root):
    run_id = uuid.uuid4()
    ws = await create_scratch_workspace(run_id)

    assert ws.branch == f"asep/run-{run_id.hex[:8]}"
    assert await run_git(ws.path, "branch", "--show-current") == ws.branch
    assert ws.base_sha  # the empty initial commit anchors diffs
