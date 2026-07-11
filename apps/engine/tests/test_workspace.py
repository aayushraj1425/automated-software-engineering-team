"""Workspace manager: clone per run, fresh branch, safe removal.

Uses a local git repository as the origin so no network is involved.
"""

import subprocess
import uuid

import pytest

from engine.config import get_settings
from engine.workspace.manager import (
    WorkspaceError,
    create_workspace,
    load_workspace,
    remove_workspace,
    run_git,
)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def origin(tmp_path):
    """A tiny local repository standing in for the user's GitHub repo."""
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@test.local")
    (repo / "README.md").write_text("# Demo repo\n")
    (repo / "app.py").write_text("print('hello')\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial commit")
    return repo


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(root))
    return root


async def test_create_clone_branch_and_remove(origin, workspace_root):
    run_id = uuid.uuid4()
    ws = await create_workspace(run_id, str(origin))

    assert ws.path == (workspace_root / str(run_id)).resolve()
    assert (ws.path / "README.md").read_text() == "# Demo repo\n"
    assert ws.branch == f"asep/run-{run_id.hex[:8]}"
    current = await run_git(ws.path, "branch", "--show-current")
    assert current == ws.branch

    remove_workspace(run_id)
    assert not ws.path.exists()


async def test_commits_in_the_workspace_do_not_touch_the_origin(origin, workspace_root):
    run_id = uuid.uuid4()
    ws = await create_workspace(run_id, str(origin))

    (ws.path / "new_feature.py").write_text("# added by an agent\n")
    await run_git(ws.path, "add", ".")
    await run_git(ws.path, "commit", "-m", "agent change")

    assert not (origin / "new_feature.py").exists()
    origin_log = subprocess.run(
        ["git", "log", "--oneline"], cwd=origin, capture_output=True, text=True
    ).stdout
    assert "agent change" not in origin_log

    remove_workspace(run_id)


async def test_clone_failure_raises_a_readable_error(workspace_root, tmp_path):
    # An existing folder that is not a git repository passes the URL guard
    # but fails the clone itself — the git error must surface readably.
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    with pytest.raises(WorkspaceError) as err:
        await create_workspace(uuid.uuid4(), str(not_a_repo))
    assert "git clone failed" in str(err.value)


async def test_a_missing_repository_path_is_rejected_before_git_runs(workspace_root, tmp_path):
    with pytest.raises(WorkspaceError) as err:
        await create_workspace(uuid.uuid4(), str(tmp_path / "does-not-exist"))
    assert "not cloneable" in str(err.value)


async def test_removing_a_missing_workspace_is_fine(workspace_root):
    remove_workspace(uuid.uuid4())  # must not raise


async def test_reopening_a_workspace_after_the_approval_pause(origin, workspace_root):
    run_id = uuid.uuid4()
    created = await create_workspace(run_id, str(origin))

    reopened = load_workspace(run_id, created.branch, created.base_sha)
    assert reopened == created

    remove_workspace(run_id)
    with pytest.raises(WorkspaceError, match="missing"):
        load_workspace(run_id, created.branch, created.base_sha)
