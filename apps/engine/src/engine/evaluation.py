"""Golden-task evaluation: measure the agent team on the fixture service.

Three fixed tasks run through the real pipeline (plan, auto-approve, execute,
review) against a fresh copy of fixtures/demo-service. Each run is scored on
mechanics — planned, completed, committed — and, when a real model is used,
on whether the diff actually contains the expected change. With LLM_FAKE=1
the diff check is skipped (offline engineers write placeholder files), so the
harness doubles as an offline pipeline smoke.
"""

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.agents.runner import execute_tasks, plan_run
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun, Repository
from engine.db.session import session_scope
from engine.workspace.manager import run_git, workspaces_root

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "demo-service"

GOLDEN_TASKS: tuple[dict[str, Any], ...] = (
    {
        "name": "Add a statistics endpoint",
        "request": (
            "Add GET /stats to the API in app/main.py returning JSON "
            '{"count": <number of items>}. Add a test for it in tests/test_app.py.'
        ),
        "expect_in_diff": ["/stats", "count"],
    },
    {
        "name": "Fix the out-of-range item bug",
        "request": (
            "GET /items/3 crashes with a 500 error. Out-of-range item ids must "
            "return 404. Find and fix the bug in app/main.py and add a "
            "regression test."
        ),
        "expect_in_diff": ["item_id"],
    },
    {
        "name": "Add a configurable item limit",
        "request": (
            "Add a max_items setting to app/config.py (default 10) and make "
            "GET /items return at most that many items."
        ),
        "expect_in_diff": ["max_items"],
    },
)


@dataclass
class TaskScore:
    name: str
    planned: bool = False
    completed: bool = False
    committed: bool = False
    diff_matched: bool | None = None  # None: not judged (offline mode)
    error: str | None = None

    @property
    def passed(self) -> bool:
        checks = [self.planned, self.completed, self.committed]
        if self.diff_matched is not None:
            checks.append(self.diff_matched)
        return all(checks)


def prepare_fixture_repo(target: Path) -> Path:
    """A fresh git repository holding a copy of the fixture service."""

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)

    import shutil

    shutil.copytree(FIXTURE_DIR, target)
    _git("init", "--initial-branch=main")
    _git("config", "user.name", "Eval Fixture")
    _git("config", "user.email", "eval@asep.local")
    _git("add", ".")
    _git("commit", "-m", "demo item service")
    return target


async def run_golden_task(origin: Path, golden: dict[str, Any]) -> TaskScore:
    """One golden task through the full pipeline, auto-approving the plan."""
    score = TaskScore(name=golden["name"])

    async with session_scope() as session:
        repo = Repository(owner_id="eval-harness", url=str(origin))
        session.add(repo)
        await session.flush()
        run = AgentRun(
            user_id="eval-harness",
            repository_id=repo.id,
            request=golden["request"],
            status=RunStatus.QUEUED,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    await plan_run(run_id)

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.status != RunStatus.AWAITING_APPROVAL:
            score.error = run.error or f"planning ended in status {run.status}"
            return score
        score.planned = True
        run.status = RunStatus.EXECUTING
        session.add(AgentEvent(run_id=run_id, type="plan.approved", payload={"by": "eval-harness"}))
        await session.commit()

    await execute_tasks(run_id)

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        score.completed = run.status == RunStatus.COMPLETED
        if not score.completed:
            score.error = run.error or f"run ended in status {run.status}"
        base_sha = run.base_sha

    workspace = workspaces_root() / str(run_id)
    if base_sha and workspace.is_dir():
        commits = await run_git(workspace, "rev-list", "--count", f"{base_sha}..HEAD")
        score.committed = int(commits) > 0
        if not get_settings().llm_fake:
            diff = (await run_git(workspace, "diff", base_sha)).lower()
            score.diff_matched = all(
                expected.lower() in diff for expected in golden["expect_in_diff"]
            )
    return score


async def evaluate_team(work_dir: Path, tasks: tuple[dict[str, Any], ...] = GOLDEN_TASKS):
    """All golden tasks against one fresh fixture repository; a list of scores."""
    origin = prepare_fixture_repo(work_dir / f"fixture-origin-{uuid.uuid4().hex[:8]}")
    return [await run_golden_task(origin, golden) for golden in tasks]
