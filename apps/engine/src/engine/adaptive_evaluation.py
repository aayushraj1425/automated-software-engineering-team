"""Runnable Quick/Standard/Complex acceptance checks against disposable fixtures."""

import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from engine.agents.runner import execute_tasks, plan_run
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import session_scope
from engine.evaluation import prepare_fixture_repo
from engine.workspace.manager import run_git, workspaces_root

ADAPTIVE_GOLDEN_TASKS = (
    {
        "name": "Quick handler rename",
        "complexity": "quick",
        "request": (
            "Rename the healthz handler function to health_check "
            "without changing its route behavior. Keep tests passing."
        ),
        "expected": ["health_check"],
    },
    {
        "name": "Standard statistics endpoint",
        "complexity": "standard",
        "request": (
            'Add GET /stats in app/main.py returning {"count": <number of items>} and add a test.'
        ),
        "expected": ["/stats", "count"],
    },
    {
        "name": "Complex configurable item limit",
        "complexity": "complex",
        "request": (
            "Add max_items (default 10) to app/config.py and enforce it on GET /items "
            "in app/main.py. Update tests and show the item limit in web/app.js. "
            "Coordinate the API and frontend design."
        ),
        "expected": ["max_items", "web/app.js"],
    },
)


@dataclass
class AdaptiveScore:
    name: str
    requested_complexity: str
    run_id: str
    fake: bool
    planned: bool = False
    completed: bool = False
    design_note: bool = False
    task_levels: bool = False
    committed: bool = False
    diff_matched: bool | None = None
    cost_usd: float = 0.0
    stages: list[str] = field(default_factory=list)
    actual_complexity: str | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        checks = [self.planned, self.completed, self.committed, self.task_levels]
        if self.requested_complexity == "complex":
            checks.append(self.design_note)
            checks.append("principal_review" in self.stages)
        if self.requested_complexity == "quick":
            checks.append(self.actual_complexity == "quick")
        if self.diff_matched is not None:
            checks.append(self.diff_matched)
        return all(checks)

    def as_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


async def evaluate_adaptive_team(directory: Path) -> list[AdaptiveScore]:
    """No cloud auto-approval: deployment validation is a separate explicit gate."""
    directory.mkdir(parents=True, exist_ok=True)
    scores = []
    for task in ADAPTIVE_GOLDEN_TASKS:
        origin = prepare_fixture_repo(directory / f"origin-{uuid.uuid4().hex[:10]}")
        async with session_scope() as db:
            repo = Repository(owner_id="adaptive-eval", url=str(origin))
            db.add(repo)
            await db.flush()
            run = AgentRun(
                user_id="adaptive-eval",
                repository_id=repo.id,
                request=task["request"],
                complexity=task["complexity"],
                preview_requested=False,
                max_cost_usd=Decimal("2.00"),
                status=RunStatus.QUEUED,
            )
            db.add(run)
            await db.commit()
            run_id = run.id
        score = AdaptiveScore(
            task["name"], task["complexity"], str(run_id), get_settings().llm_fake
        )
        await plan_run(run_id)
        async with session_scope() as db:
            run = await db.get(AgentRun, run_id)
            assert run is not None
            score.planned = run.status == RunStatus.AWAITING_APPROVAL
            score.design_note = bool(run.design_note)
            if score.planned:
                run.status = RunStatus.EXECUTING
                db.add(
                    AgentEvent(run_id=run_id, type="plan.approved", payload={"by": "adaptive-eval"})
                )
                await db.commit()
            else:
                score.error = run.error or f"Planning stopped in {run.status}"
        if score.planned:
            await execute_tasks(run_id)
        async with session_scope() as db:
            run = await db.get(AgentRun, run_id)
            assert run is not None
            score.completed = run.status == RunStatus.COMPLETED
            score.cost_usd = float(run.total_cost_usd or 0)
            score.stages = list(run.stages_completed or [])
            tasks = list(
                (await db.execute(select(AgentTask).where(AgentTask.run_id == run_id))).scalars()
            )
            score.task_levels = bool(tasks) and all(task.level and task.model for task in tasks)
            score.actual_complexity = run.complexity
            if not score.completed:
                score.error = run.error or f"Execution stopped in {run.status}"
            base_sha = run.base_sha
        workspace = workspaces_root() / str(run_id)
        if base_sha and workspace.is_dir():
            score.committed = (
                int(await run_git(workspace, "rev-list", "--count", f"{base_sha}..HEAD")) > 0
            )
            if not score.fake:
                diff = (await run_git(workspace, "diff", base_sha)).lower()
                score.diff_matched = all(term.lower() in diff for term in task["expected"])
        scores.append(score)
    return scores
