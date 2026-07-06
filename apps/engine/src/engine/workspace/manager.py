"""Workspaces: each run gets its own clone of the repository.

A workspace is a folder under WORKSPACES_DIR named after the run id, holding
a shallow git clone with a fresh branch (asep/run-<id>). Agents work only
inside this folder — the path jail enforces that — so the user's real
repository is never touched until a pull request is opened.
"""

import asyncio
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)


class WorkspaceError(Exception):
    """Cloning or a git command failed; the message is safe to show the user."""


@dataclass(frozen=True)
class Workspace:
    run_id: uuid.UUID
    path: Path
    branch: str
    base_sha: str  # the commit the clone started from — diffs measure against this


def workspaces_root() -> Path:
    return Path(get_settings().workspaces_dir).resolve()


async def run_git(cwd: Path, *args: str) -> str:
    """Run one git command inside `cwd` and return its output.

    Runs in a thread with blocking subprocess: the engine uses the Windows
    Selector event loop (psycopg needs it), which cannot spawn async
    subprocesses — asyncio.create_subprocess_exec would crash here.
    """

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 — fixed executable, no shell
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )

    proc = await asyncio.to_thread(_run)
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {out[:500]}")
    return out


async def create_workspace(run_id: uuid.UUID, repo_url: str) -> Workspace:
    """Clone the repository and check out a fresh branch for this run."""
    path = workspaces_root() / str(run_id)
    if path.exists():
        remove_workspace(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    branch = f"asep/run-{run_id.hex[:8]}"
    await run_git(path.parent, "clone", "--depth", "1", repo_url, str(path))
    await run_git(path, "checkout", "-b", branch)
    # Commits made by agents are attributed to the platform, not to the user.
    await run_git(path, "config", "user.name", "ASEP Agent Team")
    await run_git(path, "config", "user.email", "agents@asep.local")
    base_sha = await run_git(path, "rev-parse", "HEAD")
    log.info("workspace.created", run_id=str(run_id), path=str(path), branch=branch)
    return Workspace(run_id=run_id, path=path, branch=branch, base_sha=base_sha)


async def create_scratch_workspace(run_id: uuid.UUID) -> Workspace:
    """A fresh local repository for offline runs (LLM_FAKE) — no clone, no network."""
    path = workspaces_root() / str(run_id)
    if path.exists():
        remove_workspace(run_id)
    path.mkdir(parents=True)

    branch = f"asep/run-{run_id.hex[:8]}"
    await run_git(path, "init", f"--initial-branch={branch}")
    await run_git(path, "config", "user.name", "ASEP Agent Team")
    await run_git(path, "config", "user.email", "agents@asep.local")
    await run_git(path, "commit", "--allow-empty", "-m", "initialize run workspace")
    base_sha = await run_git(path, "rev-parse", "HEAD")
    log.info("workspace.scratch_created", run_id=str(run_id), path=str(path))
    return Workspace(run_id=run_id, path=path, branch=branch, base_sha=base_sha)


async def push_branch(ws: Workspace) -> bool:
    """Push the run branch to origin; False when there is no origin (scratch
    workspaces). GitHub pushes authenticate with GITHUB_TOKEN."""
    remotes = await run_git(ws.path, "remote")
    if "origin" not in remotes.split():
        return False
    target = "origin"
    url = await run_git(ws.path, "remote", "get-url", "origin")
    token = get_settings().github_token
    if token and url.startswith("https://github.com/"):
        target = url.replace("https://", f"https://x-access-token:{token}@", 1)
    try:
        await run_git(ws.path, "push", target, ws.branch)
    except WorkspaceError as exc:
        # git may echo the push URL; never let the token reach logs or the UI
        raise WorkspaceError(str(exc).replace(token, "***") if token else str(exc)) from None
    log.info("workspace.branch_pushed", run_id=str(ws.run_id), branch=ws.branch)
    return True


def load_workspace(run_id: uuid.UUID, branch: str, base_sha: str) -> Workspace:
    """Reopen the workspace created during planning (execution runs later,
    after the human approves the plan)."""
    path = workspaces_root() / str(run_id)
    if not path.is_dir():
        raise WorkspaceError(f"workspace for run {run_id} is missing")
    return Workspace(run_id=run_id, path=path, branch=branch, base_sha=base_sha)


def remove_tree(path: Path) -> None:
    """Delete a folder tree (git marks some files read-only on Windows)."""

    def _make_writable(func, p, _exc):  # noqa: ANN001
        Path(p).chmod(stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=_make_writable)


def remove_workspace(run_id: uuid.UUID) -> None:
    """Delete a run's workspace folder."""
    path = workspaces_root() / str(run_id)
    if not path.exists():
        return
    remove_tree(path)
    log.info("workspace.removed", run_id=str(run_id))
