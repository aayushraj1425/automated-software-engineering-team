"""Team templates and per-run rosters (docs/architecture/agents/ADAPTIVE_TEAM_RUNTIME.md).

A template lists the fixed seats and the ordered stages of a run. A roster is the
template's seats plus one seat for every distinct role and level on the run's task
board, each with the model the router picked for it. Nothing here calls a model:
selection is deterministic over the catalog, the run owner's keys, the organization's
policy and the human's per-seat overrides.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.quick_team import quick_template
from engine.agents.registry import get_agent_spec
from engine.agents.teams_types import Seat, StageName, TeamTemplate
from engine.db.enums import AgentRole, Complexity, TaskStatus
from engine.db.models import AgentRun, AgentTask
from engine.llm.catalog import ModelSelection, SeatLevel
from engine.llm.keys import load_provider_keys, provider_keys_var
from engine.llm.policy import load_org_model_policy
from engine.llm.router import model_router

# Levels the Product Manager may give a task; Principal and Support never take tasks.
TASK_LEVELS = (SeatLevel.ENGINEER, SeatLevel.SENIOR)

_PREVIEW_INTENT = re.compile(r"\b(deploy\w*|preview|cloud|staging|smoke)\b", re.I)


def seat_key(role: AgentRole | str, level: SeatLevel | str) -> str:
    return f"{AgentRole(role).value}:{SeatLevel(level).value}"


def _seat(role: AgentRole, level: SeatLevel | None = None) -> Seat:
    level = level or get_agent_spec(role).seat_level
    return Seat(key=seat_key(role, level), role=role, level=level)


def template_name_for(complexity: str | None, test_only: bool) -> str:
    """The template a run uses. Report-only requests keep the test_report team
    no matter what the complexity label says."""
    if test_only:
        return "test_report"
    if complexity == Complexity.QUICK:
        return "quick"
    if complexity == Complexity.COMPLEX:
        return "complex"
    return "standard"


def _standard_template() -> TeamTemplate:
    return TeamTemplate(
        name="standard",
        complexity=Complexity.STANDARD,
        seats=(
            _seat(AgentRole.PRODUCT_MANAGER),
            _seat(AgentRole.REVIEWER),
            _seat(AgentRole.QA),
        ),
        stages=(
            StageName.PLAN,
            StageName.BUILD,
            StageName.REVIEW,
            StageName.SANDBOX,
            StageName.SECURITY,
            StageName.DEPENDENCY,
            StageName.PUBLISH,
        ),
    )


def _complex_template() -> TeamTemplate:
    return TeamTemplate(
        name="complex",
        complexity=Complexity.COMPLEX,
        seats=(
            _seat(AgentRole.PRINCIPAL_ENGINEER),
            _seat(AgentRole.PRODUCT_MANAGER),
            _seat(AgentRole.REVIEWER),
            _seat(AgentRole.QA),
            _seat(AgentRole.RELEASE_ENGINEER),
        ),
        # Scans sit before the preview deploy so nothing unscanned reaches a cluster.
        stages=(
            StageName.DESIGN,
            StageName.PLAN,
            StageName.BUILD,
            StageName.REVIEW,
            StageName.PRINCIPAL_REVIEW,
            StageName.SANDBOX,
            StageName.SECURITY,
            StageName.DEPENDENCY,
            StageName.PREVIEW_DEPLOY,
            StageName.CLOUD_TESTS,
            StageName.PUBLISH,
        ),
    )


def get_team_template(name: str) -> TeamTemplate:
    if name == "quick":
        return quick_template(False)
    if name == "test_report":
        return quick_template(True)
    if name == "standard":
        return _standard_template()
    if name == "complex":
        return _complex_template()
    raise ValueError(f"unknown team template {name!r}")


def preview_wanted(run: AgentRun) -> bool:
    """An explicit request wins; otherwise infer it from the words of the request."""
    if run.preview_requested is not None:
        return bool(run.preview_requested)
    return bool(_PREVIEW_INTENT.search(run.request))


def remaining_budget(run: AgentRun) -> float | None:
    if run.max_cost_usd is None:
        return None
    left = run.max_cost_usd - Decimal(run.total_cost_usd or 0)
    return float(left) if left > 0 else None


@asynccontextmanager
async def owner_keys(session: AsyncSession, run: AgentRun) -> AsyncIterator[None]:
    """Make the run owner's provider keys visible to the router for one block,
    so a seat only counts as available when its owner can really call it."""
    keys = await load_provider_keys(session, run.user_id, run.org_id)
    token = provider_keys_var.set(keys)
    try:
        yield
    finally:
        provider_keys_var.reset(token)


async def load_model_policy(session: AsyncSession, run: AgentRun) -> tuple[dict[str, str], bool]:
    """(level pins, allow open source in auto) for the run's organization."""
    policy = await load_org_model_policy(session, run.org_id)
    return policy.level_pins, policy.allow_open_source_auto


async def resolve_run_seat(
    session: AsyncSession,
    run: AgentRun,
    role: AgentRole | str,
    level: SeatLevel | str | None = None,
    budget: float | None = None,
) -> ModelSelection:
    """The model for one seat: human override, then organization pin, then auto.
    Provider keys come from the caller's context (see `owner_keys`)."""
    level = SeatLevel(level) if level else get_agent_spec(role).seat_level
    key = seat_key(role, level)
    pinned = (run.model_overrides or {}).get(key)
    org_pins, allow_open_source = await load_model_policy(session, run)
    kwargs: dict[str, Any] = {}
    if allow_open_source:
        kwargs["allow_open_source_auto"] = True
    return model_router.resolve_seat(
        level,
        {level.value: pinned} if pinned else None,
        budget,
        org_pins or None,
        **kwargs,
    )


async def assemble_run_team(session: AsyncSession, run: AgentRun) -> list[dict]:
    """Build the roster, save it on the run, and record each task's level model.

    Raises ValueError (ModelSelectionError) when a pinned model is unknown or
    unavailable, so the roster endpoint can answer 422 instead of saving it.
    """
    template = get_team_template(run.team_template)
    tasks: list[AgentTask] = []
    if isinstance(run.id, uuid.UUID):
        tasks = list(
            (
                await session.execute(
                    select(AgentTask)
                    .where(AgentTask.run_id == run.id, AgentTask.status != TaskStatus.SKIPPED)
                    .order_by(AgentTask.sequence)
                )
            )
            .scalars()
            .all()
        )
    seats: dict[str, Seat] = {seat.key: seat for seat in template.seats}
    if run.team_template == "quick" and tasks:
        # A human can shrink an existing board to one frontend/devops seat.
        seats = {}
    for task in tasks:
        seat = _seat(AgentRole(task.role), SeatLevel(task.level))
        seats.setdefault(seat.key, seat)

    budget = remaining_budget(run)
    roster: list[dict] = []
    models: dict[str, str] = {}
    async with owner_keys(session, run):
        for seat in seats.values():
            selection = await resolve_run_seat(session, run, seat.role, seat.level, budget)
            models[seat.key] = selection.model
            roster.append(
                Seat(
                    key=seat.key,
                    role=seat.role,
                    level=seat.level,
                    model=selection.model,
                    reason=selection.reason,
                ).model_dump(mode="json")
            )
    for task in tasks:
        if task.status != TaskStatus.DONE:
            task.model = models.get(seat_key(task.role, task.level))
    run.team = roster
    return roster
