"""Executes one agent run from start to finish.

Planning: clone the repository into a jailed per-run workspace, let the
Product Manager write the plan, save the task board, and stop at
awaiting_approval. Execution (after the human approves): reopen the workspace
and let the Supervisor route each task to the engineer agents. Every status
change lands in Postgres as an event, so the UI timeline is a full audit of
the run. An arq worker replaces the in-process background task when runs get
long (backlog).
"""

import uuid
from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from opentelemetry import trace
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.audit import audit_user_var, build_audit_log
from engine.agents.engineer import execute_revision, execute_task
from engine.agents.loop import LlmUsage
from engine.agents.principal import review_against_design, write_design_note
from engine.agents.product_manager import create_plan
from engine.agents.pull_request import build_pull_request_body
from engine.agents.qa import fix_failing_tests
from engine.agents.release_readiness import write_readiness_note
from engine.agents.reviewer import APPROVE, REQUEST_CHANGES, review_run
from engine.agents.supervisor import ExecutionOutcome, TaskState, build_supervisor_graph
from engine.agents.teams import (
    assemble_run_team,
    get_team_template,
    preview_wanted,
    resolve_run_seat,
    template_name_for,
)
from engine.agents.teams_types import StageName
from engine.agents.triage import (
    Complexity,
    classify_request,
    classify_rules,
    scope_terms,
)
from engine.config import get_settings
from engine.db.enums import AgentRole, IntegrationKind, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, IndexedFile, Repository
from engine.db.session import session_scope
from engine.deploy.contracts import PreviewDeployment, PreviewOptions, SmokeResult
from engine.events.bus import publish_run_ping
from engine.github import open_pull_request, parse_github_repo
from engine.integrations import bitbucket, gitlab
from engine.integrations.hosts import host_connection, push_credential
from engine.integrations.notify import notify_run_outcome
from engine.knowledge.capture import capture_run_memory
from engine.knowledge.recall import format_memories, recall_memories
from engine.llm.catalog import ModelSelection, SeatLevel
from engine.llm.keys import load_provider_keys, provider_keys_var
from engine.llm.router import selected_model_var, selection_observer_var
from engine.sandbox.runner import SandboxResult, run_sandbox
from engine.security.dependency_scanner import scan_diff as scan_dependency_diff
from engine.security.secrets_scanner import scan_diff
from engine.workspace.manager import (
    Workspace,
    create_scratch_workspace,
    create_workspace,
    load_workspace,
    push_branch,
    run_git,
)

log = structlog.get_logger()

# No-op until the SDK is configured (OTEL_ENABLED — see engine/observability.py).
_tracer = trace.get_tracer("engine.runs")


def _now() -> datetime:
    return datetime.now(UTC)


def _emit(
    session: AsyncSession,
    run_id: uuid.UUID,
    type_: str,
    payload: dict[str, Any] | None = None,
    agent: str | None = None,
    task_id: uuid.UUID | None = None,
) -> None:
    session.add(
        AgentEvent(run_id=run_id, task_id=task_id, agent=agent, type=type_, payload=payload or {})
    )


async def _commit_and_ping(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Commit, then wake any open timeline stream (RUN_EVENT_STREAMING.md).
    The ping never raises; with Redis down the stream's heartbeat covers it."""
    await session.commit()
    await publish_run_ping(run_id)


def _set_run_status(session: AsyncSession, run: AgentRun, status: RunStatus) -> None:
    old = run.status
    run.status = status
    _emit(session, run.id, "run.status_changed", {"from": old, "to": status})


def _fail_run(session: AsyncSession, run: AgentRun, error: str) -> None:
    """The one way a run ends in failure: set the error, transition to FAILED,
    stamp the finish time, and emit run.finished. Every failure path (a crash,
    a task giving up, the reviewer refusing, either gate blocking) funnels
    through here so they can never drift apart. The caller still commits."""
    run.error = error
    _set_run_status(session, run, RunStatus.FAILED)
    run.finished_at = _now()
    _emit(session, run.id, "run.finished", {"status": run.status, "error": run.error})


def _apply_usage(run: AgentRun, usage: LlmUsage) -> None:
    run.total_input_tokens += usage.input_tokens
    run.total_output_tokens += usage.output_tokens
    run.total_cost_usd += Decimal(str(round(usage.cost_usd, 6)))


class BudgetExceeded(Exception):
    """The run spent its cost cap; no further model work may start."""


async def _persist_model_selection(
    session: AsyncSession,
    run: AgentRun,
    role: str,
    selection: ModelSelection,
    task_id: uuid.UUID | None,
) -> None:
    key = f"{role}:{selection.level.value}"
    run.team = [
        {**seat, "model": selection.model, "reason": selection.reason}
        if seat.get("key") == key
        else seat
        for seat in run.team
    ]
    if task_id is not None:
        task = await session.get(AgentTask, task_id)
        if task is not None and task.run_id == run.id:
            task.model = selection.model


def _check_budget(run: AgentRun) -> None:
    if run.max_cost_usd is not None and run.total_cost_usd >= run.max_cost_usd:
        raise BudgetExceeded(
            f"run budget of ${run.max_cost_usd} exhausted (spent ${run.total_cost_usd})"
        )


@asynccontextmanager
async def _agent_model(
    run_id: uuid.UUID,
    role: str,
    task_id: uuid.UUID | None = None,
    level: SeatLevel | str | None = None,
):
    """Select once for this agent, persist the reason, and isolate concurrent runs.

    The seat is the role at `level` (the task's level, or the role's default). The
    human's per-seat override, the organization's pins and the run owner's keys all
    apply, exactly as they did when the roster was shown for approval."""
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _check_budget(run)
        if role == AgentRole.QA and not run.test_only:
            _escalate(session, run, "Quick change needs a QA repair and independent review")
        budget = (
            float(run.max_cost_usd - run.total_cost_usd) if run.max_cost_usd is not None else None
        )
        selection = await resolve_run_seat(session, run, role, level, budget)
        await _persist_model_selection(session, run, role, selection, task_id)
        payload = asdict(selection)
        if get_settings().llm_fake:
            payload.update(
                model="fake", configured_model=selection.model, reason="offline fake mode"
            )
        _emit(session, run_id, "model.selected", payload, agent=role, task_id=task_id)
        await _commit_and_ping(session, run_id)
    token = selected_model_var.set(selection)

    async def record_fallback(pick):
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            await _persist_model_selection(session, run, role, pick, task_id)
            _emit(session, run_id, "model.selected", asdict(pick), agent=role, task_id=task_id)
            await _commit_and_ping(session, run_id)

    observer_token = selection_observer_var.set(record_fallback)
    try:
        yield selection
    finally:
        selection_observer_var.reset(observer_token)
        selected_model_var.reset(token)


def _summarize_args(args: dict[str, Any]) -> dict[str, str]:
    # File contents don't belong in the timeline — record their size instead.
    return {
        key: f"({len(str(value))} chars)" if key == "content" else str(value)[:200]
        for key, value in args.items()
    }


def _tool_observer(run_id: uuid.UUID, agent: str | None, task_id: uuid.UUID | None = None):
    """Audit trail: one tool.called event per tool invocation (ADR-0008)."""

    async def _record(name: str, args: dict[str, Any], result: str) -> None:
        summary = _summarize_args(args)
        preview = result[:200]
        ok = not result.startswith("ERROR:")
        async with session_scope() as session:
            _emit(
                session,
                run_id,
                "tool.called",
                {"tool": name, "args": summary, "ok": ok, "result": preview},
                agent=agent,
                task_id=task_id,
            )
            # The durable security mirror, written in the same transaction
            # (docs/architecture/security/AUDIT_LOG.md).
            session.add(build_audit_log(run_id, agent, task_id, name, summary, ok, preview))
            await _commit_and_ping(session, run_id)

    return _record


# How much reasoning text to keep on a timeline event — enough to read the
# rationale, capped like other event payloads
# (docs/architecture/agents/AGENT_REASONING_TIMELINE.md).
_REASONING_MAX = 2000


def _reasoning_observer(run_id: uuid.UUID, agent: str | None, task_id: uuid.UUID | None = None):
    """The agent's 'why': one agent.reasoning event per tool-calling turn that
    carried reasoning text (AGENT_REASONING_TIMELINE.md)."""

    async def _record(text: str) -> None:
        async with session_scope() as session:
            _emit(
                session,
                run_id,
                "agent.reasoning",
                {"text": text[:_REASONING_MAX]},
                agent=agent,
                task_id=task_id,
            )
            await _commit_and_ping(session, run_id)

    return _record


async def plan_run(run_id: uuid.UUID) -> None:
    """Background entrypoint after POST /v1/runs: plan, then wait for approval."""
    # The span ties every LLM call in the phase to the run (ADR-0010 post-mortems).
    with _tracer.start_as_current_span("run.plan", attributes={"asep.run_id": str(run_id)}):
        await _guarded(_plan_run, run_id)
    # A run that failed during planning still leaves memory behind; a run
    # waiting for approval is not terminal, so capture does nothing.
    await capture_run_memory(run_id)
    await notify_run_outcome(run_id)


async def execute_tasks(run_id: uuid.UUID) -> None:
    """Background entrypoint after the human approves the plan."""
    with _tracer.start_as_current_span("run.execute", attributes={"asep.run_id": str(run_id)}):
        await _guarded(_execute_tasks, run_id)
    # The run is terminal either way now — remember what happened
    # (KNOWLEDGE_AND_MEMORY.md); capture never raises.
    await capture_run_memory(run_id)
    await notify_run_outcome(run_id)


async def _guarded(work, run_id: uuid.UUID) -> None:
    """Whatever breaks inside a run must end as a failed run, never a crash."""
    try:
        await work(run_id)
    except Exception as exc:
        log.exception("run.crashed", run_id=str(run_id))
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None:
                _fail_run(session, run, str(exc)[:500] or "internal error while executing the run")
                await _commit_and_ping(session, run_id)


async def _open_workspace(run_id: uuid.UUID, repo_url: str) -> Workspace:
    # Offline mode still clones local fixture repositories; with a remote URL
    # it starts from an empty scratch repository instead of touching the network.
    if get_settings().llm_fake and not Path(repo_url).exists():
        return await create_scratch_workspace(run_id)
    return await create_workspace(run_id, repo_url)


def _escalate(session: AsyncSession, run: AgentRun, reason: str) -> None:
    if run.complexity != Complexity.QUICK:
        return
    run.complexity = Complexity.STANDARD
    run.triage_reason = f"escalated: {reason}"
    run.team_template = template_name_for(run.complexity, run.test_only)
    # Standard tests again after review, so a finished Quick sandbox no longer counts.
    run.stages_completed = [s for s in (run.stages_completed or []) if s != StageName.SANDBOX]
    _emit(
        session,
        run.id,
        "run.escalated",
        {
            "from": "quick",
            "to": "standard",
            "reason": reason,
            "team_template": run.team_template,
        },
    )


def _mark_stage(session: AsyncSession, run: AgentRun, stage: StageName) -> None:
    """Checkpoint a finished stage in the caller's transaction (a restart skips it)."""
    done = list(run.stages_completed or [])
    if stage.value not in done:
        done.append(stage.value)
        run.stages_completed = done
        _emit(session, run.id, "stage.completed", {"stage": stage.value})


async def _complete_stage(run_id: uuid.UUID, stage: StageName) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _mark_stage(session, run, stage)
        await _commit_and_ping(session, run_id)


def _team_event(
    run: AgentRun, roster: list[dict], roles: Iterable[str], reason: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "template": run.team_template,
        "complexity": run.complexity,
        "roles": sorted(set(roles)),
        "seats": roster,
    }
    if reason:
        payload["reason"] = reason
    return payload


def _team_roles(run: AgentRun, task_roles: Iterable[str], planning_role: str) -> set[str]:
    roles = set(task_roles) | {planning_role}
    if run.team_template in ("standard", "complex"):
        roles.add(str(AgentRole.REVIEWER))
    if run.team_template == "complex":
        roles.add(str(AgentRole.PRINCIPAL_ENGINEER))
    return roles


async def _triage_run(run_id: uuid.UUID, repository_id: uuid.UUID, request: str):
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        override = run.complexity
        saved_reason = run.triage_reason
        terms = scope_terms(request)
        paths = (
            list(
                (
                    await session.execute(
                        select(IndexedFile.path)
                        .where(
                            IndexedFile.repository_id == repository_id,
                            or_(*(IndexedFile.path.ilike(f"%{term}%") for term in terms)),
                        )
                        .order_by(IndexedFile.path)
                        .limit(100)
                    )
                ).scalars()
            )
            if terms
            else []
        )
    usage = LlmUsage()
    decision = classify_rules(request, paths)
    if decision is None and override is None:
        async with _agent_model(run_id, AgentRole.SUPERVISOR):
            decision = await classify_request(request, paths, usage)
    if decision is None:
        # Explicit complexity needs no classifier call; test-only remains rule-bound.
        from engine.agents.triage import TriageDecision, is_test_only

        decision = TriageDecision(
            Complexity(override), "human complexity override", is_test_only(request)
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.complexity = override or decision.complexity
        run.triage_reason = run.triage_reason or (
            "human complexity override" if override else decision.reason
        )
        run.test_only = decision.test_only
        run.team_template = template_name_for(run.complexity, run.test_only)
        _apply_usage(run, usage)
        _emit(
            session,
            run_id,
            "run.triaged",
            {
                "complexity": run.complexity,
                "reason": run.triage_reason,
                "test_only": run.test_only,
                "source": "saved" if saved_reason else "human" if override else decision.source,
                "matched_files": len(paths),
                "team_template": run.team_template,
            },
        )
        await _commit_and_ping(session, run_id)
        return run.complexity, run.test_only


async def _write_design(run_id: uuid.UUID, request: str, ws: Workspace) -> str:
    """The Principal Engineer's design note: saved on the run, checkpointed, and
    recorded on the timeline. Read-only; the note is plain text for the planner."""
    usage = LlmUsage()
    async with _agent_model(run_id, AgentRole.PRINCIPAL_ENGINEER):
        note = await write_design_note(
            request,
            ws,
            usage,
            _tool_observer(run_id, AgentRole.PRINCIPAL_ENGINEER),
            _reasoning_observer(run_id, AgentRole.PRINCIPAL_ENGINEER),
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.design_note = note
        _apply_usage(run, usage)
        _mark_stage(session, run, StageName.DESIGN)
        _emit(
            session,
            run_id,
            "design.created",
            {"chars": len(note), "note": note[:2000]},
            agent=AgentRole.PRINCIPAL_ENGINEER,
        )
        await _commit_and_ping(session, run_id)
    return note


async def _plan_run(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return
        # Disconnect is refused while a run is active, so an active run's
        # repository always exists (RUN_HISTORY_RETENTION.md).
        assert run.repository_id is not None
        repo = await session.get(Repository, run.repository_id)
        assert repo is not None
        repo_url = repo.url
        repository_id = run.repository_id
        request = run.request
        # The run owner's provider keys ride this task's context to the
        # ModelRouter (PROVIDER_KEYS.md); no keys means the .env keys apply.
        provider_keys_var.set(await load_provider_keys(session, run.user_id, run.org_id))
        # …and the owner rides the context to the tool-call audit trail, so a
        # row stays attributable after the run is gone (AUDIT_LOG.md).
        audit_user_var.set(run.user_id)
        run.started_at = _now()
        _emit(session, run_id, "run.started", {"request": run.request})
        _set_run_status(session, run, RunStatus.PLANNING)
        await _commit_and_ping(session, run_id)

    complexity, test_only = await _triage_run(run_id, repository_id, request)
    ws = await _open_workspace(run_id, repo_url)
    usage = LlmUsage()
    planning_role = (
        AgentRole.BACKEND if complexity == Complexity.QUICK else AgentRole.PRODUCT_MANAGER
    )
    template = get_team_template(template_name_for(complexity, test_only))
    design_note = ""
    if StageName.DESIGN in template.stages and not test_only:
        design_note = await _write_design(run_id, request, ws)
    if test_only:
        planning_role = AgentRole.QA
        plan = {
            "summary": (
                "Run the repository's recognized test suite in the sandbox and report its result. "
                "No code changes or pull request. "
                "The report records the exact test command and any skip."
            ),
            "tasks": [
                {
                    "role": "qa",
                    "title": "Run tests and report results",
                    "description": request,
                    "level": "engineer",
                    "depends_on": [],
                }
            ],
        }
    else:
        memory = await _recall_for_planning(run_id, repository_id, request)
        async with _agent_model(run_id, planning_role):
            plan = await create_plan(
                request,
                ws,
                usage,
                _tool_observer(run_id, planning_role),
                memory=memory,
                on_reasoning=_reasoning_observer(run_id, planning_role),
                quick=complexity == Complexity.QUICK,
                design_note=design_note,
                complex_run=complexity == Complexity.COMPLEX,
            )

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.branch_name = ws.branch
        run.base_sha = ws.base_sha
        if len(plan["tasks"]) > 2 or (
            run.team_template == "quick" and {t["role"] for t in plan["tasks"]} != {"backend"}
        ):
            _escalate(session, run, "Quick plan needs more than two tasks or multiple specialists")
        tasks: list[AgentTask] = []
        for sequence, item in enumerate(plan["tasks"], start=1):
            task = AgentTask(
                run_id=run_id,
                sequence=sequence,
                role=item["role"],
                level=item.get("level") or "engineer",
                title=item["title"],
                description=item["description"],
            )
            session.add(task)
            await session.flush()
            task.depends_on = [str(tasks[dep - 1].id) for dep in item["depends_on"]]
            tasks.append(task)
        run.plan = {"summary": plan["summary"], "tasks": [t.title for t in tasks]}
        _apply_usage(run, usage)
        _emit(session, run_id, "plan.created", run.plan, agent=planning_role)
        # The roster: template seats plus one seat per role and level on the board,
        # each with its model (and each task gets its model recorded).
        roster = await assemble_run_team(session, run)
        _emit(
            session,
            run_id,
            "team.assembled",
            _team_event(run, roster, _team_roles(run, (t.role for t in tasks), str(planning_role))),
        )
        _mark_stage(session, run, StageName.PLAN)
        # Stop here: nothing executes until the human approves the plan.
        _set_run_status(session, run, RunStatus.AWAITING_APPROVAL)
        await _commit_and_ping(session, run_id)


async def prepare_approval_team(run_id: uuid.UUID) -> None:
    """Finish approval preparation for a planned run the API parked in PLANNING.

    The API calls this after a complexity change (for example Standard to Complex)
    on a run that already has a plan. It writes the Principal's design note when the
    new template needs one and none exists, rebuilds the roster, and returns the run
    to AWAITING_APPROVAL. The task board is never rewritten, so the human's plan
    edits survive. Failures end the run through the usual guard."""
    await _guarded(_prepare_approval_team, run_id)
    await capture_run_memory(run_id)
    await notify_run_outcome(run_id)


async def _prepare_approval_team(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        # Only a planned run the API parked in PLANNING; anything else is a stale call.
        if run is None or run.status != RunStatus.PLANNING or not run.plan:
            return
        if not run.branch_name or not run.base_sha:
            return
        provider_keys_var.set(await load_provider_keys(session, run.user_id, run.org_id))
        audit_user_var.set(run.user_id)
        request, branch, base_sha = run.request, run.branch_name, run.base_sha
        template = get_team_template(run.team_template)
        needs_design = (
            StageName.DESIGN in template.stages and not run.design_note and not run.test_only
        )
    if needs_design:
        await _write_design(run_id, request, load_workspace(run_id, branch, base_sha))
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.status != RunStatus.PLANNING:
            return
        roster = await assemble_run_team(session, run)
        rows = (
            await session.execute(select(AgentTask).where(AgentTask.run_id == run_id))
        ).scalars()
        task_roles = [r.role for r in rows if r.status != TaskStatus.SKIPPED]
        _emit(
            session,
            run_id,
            "team.assembled",
            _team_event(
                run,
                roster,
                _team_roles(run, task_roles, str(AgentRole.PRODUCT_MANAGER)),
                reason="complexity changed before approval",
            ),
        )
        _set_run_status(session, run, RunStatus.AWAITING_APPROVAL)
        await _commit_and_ping(session, run_id)


async def _recall_for_planning(run_id: uuid.UUID, repository_id: uuid.UUID, request: str) -> str:
    """Long-term memory feeding agent context (KNOWLEDGE_AND_MEMORY.md): the
    memories most relevant to the request, formatted for the planner's prompt.
    The memory.recalled event makes the recall visible on the run timeline.
    Recall failing must not fail the run — planning just proceeds without it."""
    try:
        async with session_scope() as session:
            memories = await recall_memories(session, repository_id, request)
            if memories:
                _emit(
                    session,
                    run_id,
                    "memory.recalled",
                    {
                        "count": len(memories),
                        "memories": [
                            {"kind": m.kind, "title": m.title, "score": m.score} for m in memories
                        ],
                    },
                    agent=AgentRole.PRODUCT_MANAGER,
                )
                await _commit_and_ping(session, run_id)
            return format_memories(memories)
    except Exception:
        log.exception("memory.recall_failed", run_id=str(run_id))
        return ""


_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)


@dataclass
class _Exec:
    """What every stage handler needs; handlers re-read mutable run state from Postgres."""

    run_id: uuid.UUID
    request: str
    plan_summary: str
    repo_url: str
    default_branch: str
    ws: Workspace


async def _execute_tasks(run_id: uuid.UUID) -> None:
    # The human approved — reopen the workspace and walk the template's stages.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.EXECUTING:
            return
        assert run.repository_id is not None  # disconnect refused while active
        repo = await session.get(Repository, run.repository_id)
        assert repo is not None
        # The run owner's provider keys, for every model call this task makes.
        provider_keys_var.set(await load_provider_keys(session, run.user_id, run.org_id))
        audit_user_var.set(run.user_id)  # attributes the tool-call audit trail (AUDIT_LOG.md)
        ctx = _Exec(
            run_id=run_id,
            request=run.request,
            plan_summary=str((run.plan or {}).get("summary", "")),
            repo_url=repo.url,
            default_branch=repo.default_branch,
            ws=load_workspace(run_id, run.branch_name or "", run.base_sha or ""),
        )

    assembled_for: str | None = None
    while True:
        stage, assembled_for = await _next_stage(run_id, assembled_for)
        if stage is None:
            break
        # A handler returns False when it ended the run (failed) or paused it for a human.
        if not await _STAGE_HANDLERS[stage](ctx):
            return
        await _complete_stage(run_id, stage)
    await _finish_run(run_id)


async def _next_stage(
    run_id: uuid.UUID, assembled_for: str | None
) -> tuple[StageName | None, str | None]:
    """The first stage of the run's current template that is not checkpointed yet.

    The template is re-read every time, so an escalation mid-run switches the stage
    list (and rebuilds the roster) without special cases."""
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.status in _TERMINAL:
            return None, assembled_for
        if not run.team or run.team_template != assembled_for:
            roster = await assemble_run_team(session, run)
            if assembled_for is not None:
                rows = (
                    await session.execute(select(AgentTask).where(AgentTask.run_id == run_id))
                ).scalars()
                roles = _team_roles(run, [r.role for r in rows], str(AgentRole.PRODUCT_MANAGER))
                _emit(
                    session,
                    run_id,
                    "team.assembled",
                    _team_event(run, roster, roles, reason=run.triage_reason),
                )
            await _commit_and_ping(session, run_id)
        completed = set(run.stages_completed or [])
        for stage in get_team_template(run.team_template).stages:
            # Planning finished before approval; an existing note means design is done too.
            if stage == StageName.PLAN or (stage == StageName.DESIGN and run.design_note):
                continue
            if stage.value not in completed:
                return stage, run.team_template
        return None, run.team_template


async def _finish_run(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.status in _TERMINAL:
            return
        _set_run_status(session, run, RunStatus.COMPLETED)
        run.finished_at = _now()
        _emit(session, run_id, "run.finished", {"status": run.status, "error": run.error})
        await _commit_and_ping(session, run_id)


async def _stage_design(ctx: _Exec) -> bool:
    # Only reached when the human raised the complexity after planning and the
    # note was not written then (prepare_approval_team normally does that).
    await _write_design(ctx.run_id, ctx.request, ctx.ws)
    return True


async def _stage_build(ctx: _Exec) -> bool:
    run_id = ctx.run_id
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(AgentTask).where(AgentTask.run_id == run_id).order_by(AgentTask.sequence)
                )
            )
            .scalars()
            .all()
        )
        board = [_to_task_state(t) for t in rows]
    known_ids = {t["id"] for t in board}
    graph = build_supervisor_graph(_make_task_executor(run_id, ctx.request, ctx.ws, known_ids))
    final = await graph.ainvoke(
        {"tasks": board, "current_task_id": None, "failure": None},
        {"recursion_limit": 100},
    )

    # Sync the task board; a failed run ends here, a clean one goes to review.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        rows = (
            (await session.execute(select(AgentTask).where(AgentTask.run_id == run_id)))
            .scalars()
            .all()
        )
        by_id = {str(row.id): row for row in rows}
        for state in final["tasks"]:
            row = by_id[state["id"]]
            if row.status != state["status"]:
                _emit(
                    session,
                    run_id,
                    "task.status_changed",
                    {"from": row.status, "to": state["status"]},
                    task_id=row.id,
                )
                row.status = state["status"]
                row.attempts = state["attempts"]
        if final["failure"] is not None:
            _fail_run(session, run, final["failure"])
            await _commit_and_ping(session, run_id)
            return False
        if run.status != RunStatus.REVIEWING:
            _set_run_status(session, run, RunStatus.REVIEWING)
        await _commit_and_ping(session, run_id)
    return True


async def _role_level(run_id: uuid.UUID, role: str) -> SeatLevel:
    """The level a role's revision runs at: Senior when any of its tasks was Senior."""
    async with session_scope() as session:
        levels = (
            await session.execute(
                select(AgentTask.level).where(AgentTask.run_id == run_id, AgentTask.role == role)
            )
        ).scalars()
        return SeatLevel.SENIOR if SeatLevel.SENIOR in set(levels) else SeatLevel.ENGINEER


async def _revision_round(ctx: _Exec, findings: list[dict]) -> None:
    """One revision round: each role fixes its own findings."""
    run_id = ctx.run_id
    findings_by_role: dict[str, list[str]] = {}
    for finding in findings:
        findings_by_role.setdefault(finding["role"], []).append(finding["issue"])
    for role, issues in findings_by_role.items():
        before = await run_git(ctx.ws.path, "rev-parse", "HEAD")
        usage = LlmUsage()
        async with _agent_model(run_id, role, level=await _role_level(run_id, role)):
            summary = await execute_revision(
                role,
                issues,
                ctx.request,
                ctx.ws,
                usage,
                _tool_observer(run_id, role),
                _reasoning_observer(run_id, role),
            )
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            if run.team_template == "complex" and before != await run_git(
                ctx.ws.path, "rev-parse", "HEAD"
            ):
                run.stages_completed = [
                    stage
                    for stage in run.stages_completed
                    if stage not in (StageName.SANDBOX, StageName.SECURITY, StageName.DEPENDENCY)
                ]
            _apply_usage(run, usage)
            _emit(
                session,
                run_id,
                "review.revision",
                {"role": role, "findings": len(issues), "summary": summary[:500]},
                agent=role,
            )
            await _commit_and_ping(session, run_id)


async def _stage_review(ctx: _Exec) -> bool:
    verdict = await _review(ctx.run_id, ctx.request, ctx.plan_summary, ctx.ws)
    if verdict["verdict"] == REQUEST_CHANGES:
        # One revision round, then the second verdict is final.
        await _revision_round(ctx, verdict["findings"])
        verdict = await _review(ctx.run_id, ctx.request, ctx.plan_summary, ctx.ws)
    if verdict["verdict"] != APPROVE:
        await _fail(ctx.run_id, "the reviewer did not approve the changes after one revision")
        return False
    return True


async def _stage_principal_review(ctx: _Exec) -> bool:
    async with session_scope() as session:
        run = await session.get(AgentRun, ctx.run_id)
        assert run is not None
        design_note = run.design_note or ""
    verdict = await _principal_review(ctx, design_note)
    if verdict["verdict"] == REQUEST_CHANGES:
        await _revision_round(ctx, verdict["findings"])
        verdict = await _principal_review(ctx, design_note)
    if verdict["verdict"] != APPROVE:
        await _fail(
            ctx.run_id, "the Principal Engineer did not approve the changes after one revision"
        )
        return False
    return True


async def _principal_review(ctx: _Exec, design_note: str) -> dict:
    run_id = ctx.run_id
    usage = LlmUsage()
    async with _agent_model(run_id, AgentRole.PRINCIPAL_ENGINEER):
        verdict = await review_against_design(
            ctx.request,
            ctx.plan_summary,
            design_note,
            ctx.ws,
            usage,
            _tool_observer(run_id, AgentRole.PRINCIPAL_ENGINEER),
            _reasoning_observer(run_id, AgentRole.PRINCIPAL_ENGINEER),
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _apply_usage(run, usage)
        _emit(
            session,
            run_id,
            "review.verdict",
            {
                "verdict": verdict["verdict"],
                "findings": [f["issue"][:300] for f in verdict["findings"]],
                "stage": "principal_review",
            },
            agent=AgentRole.PRINCIPAL_ENGINEER,
        )
        await _commit_and_ping(session, run_id)
    return verdict


async def _fail(run_id: uuid.UUID, error: str) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _fail_run(session, run, error)
        await _commit_and_ping(session, run_id)


async def _stage_sandbox(ctx: _Exec) -> bool:
    return await _sandbox_gate(ctx.run_id, ctx.request, ctx.ws)  # False: tests did not pass


async def _stage_security(ctx: _Exec) -> bool:
    return await _security_gate(ctx.run_id, ctx.ws)  # False: a leaked secret blocks the PR


async def _stage_dependency(ctx: _Exec) -> bool:
    return await _dependency_gate(ctx.run_id, ctx.ws)  # False: a vulnerable dependency blocks it


async def _stage_test_report(ctx: _Exec) -> bool:
    await _execute_test_report(ctx.run_id, ctx.ws)
    return False  # the report completes (or fails) the run itself


async def _stage_publish(ctx: _Exec) -> bool:
    async with session_scope() as session:
        run = await session.get(AgentRun, ctx.run_id)
        assert run is not None
        if run.pr_url:  # a recovered run never opens a second request
            return True
        quick = run.team_template == "quick"
    changed = bool((await run_git(ctx.ws.path, "diff", ctx.ws.base_sha)).strip())
    if not quick or changed:
        await _publish(
            ctx.run_id,
            ctx.repo_url,
            ctx.default_branch,
            ctx.request,
            ctx.plan_summary,
            ctx.ws,
        )
    return True


# ── Preview deploy (docs/architecture/agents/ADAPTIVE_TEAM_RUNTIME.md) ──────────────────────────


def _preview_options(run: AgentRun) -> PreviewOptions:
    return PreviewOptions.model_validate(run.preview_options or {})


def _scrub(text: str, secrets: dict[str, str] | None = None) -> str:
    """Bounded error text with any credential material removed."""
    for value in (secrets or {}).values():
        for piece in {value, *(line.strip() for line in value.splitlines())}:
            if len(piece) >= 6:
                text = text.replace(piece, "[redacted]")
    return " ".join(text.split())[:300]


def _smoke_evidence(smoke: SmokeResult | None) -> dict[str, Any]:
    if smoke is None:
        return {"passed": None, "checks": []}
    checks = [
        {key: str(check.get(key))[:200] for key in ("path", "status", "ok", "error", "attempts")}
        for check in smoke.checks[:10]
        if isinstance(check, dict)
    ]
    return {"passed": smoke.passed, "error": _scrub(smoke.error or "") or None, "checks": checks}


async def _stage_preview_deploy(ctx: _Exec) -> bool:
    """Deploy the approved commit to a preview namespace, then smoke test it.

    Without a recorded second approval nothing deploys: the run parks in
    awaiting_deploy_approval. The API sets approved_at/by/sha and resumes the run."""
    run_id = ctx.run_id
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if not preview_wanted(run):
            _emit(session, run_id, "deploy.skipped", {"reason": "no preview deployment requested"})
            await _commit_and_ping(session, run_id)
            return True
        saved = run.preview_deployment or {}
        if saved.get("status") in ("deployed", "simulated"):
            return True  # a recovered run never deploys twice
        options = _preview_options(run)
        approved_sha = run.deployment_approved_sha
        approved = bool(run.deployment_approved_at and run.deployment_approved_by and approved_sha)
        org_id = run.org_id
        design_note = run.design_note or ""

    head = (await run_git(ctx.ws.path, "rev-parse", "HEAD")).strip()
    if not approved or approved_sha is None:
        return await _request_deploy_approval(ctx, options, head, design_note)
    if head != approved_sha:
        # The approval covered a different commit; fail closed rather than deploy it.
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            run.deployment_status = "failed"
            _fail_run(
                session,
                run,
                f"workspace commit {head[:12]} differs from the approved commit "
                f"{approved_sha[:12]}; nothing was deployed",
            )
            await _commit_and_ping(session, run_id)
        return False

    fake = get_settings().llm_fake
    credentials: dict[str, str] = {}
    if not fake:
        from engine.security.preview_credentials import load_preview_credentials

        try:
            async with session_scope() as session:
                credentials = await load_preview_credentials(session, org_id)
        except ValueError as exc:
            await _fail_deploy(run_id, str(exc)[:300])
            return False

    # Checkpoint before the privileged call: a restart can tell a deploy may have begun.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.deployment_status = "deploying"
        if run.status != RunStatus.DEPLOYING:
            _set_run_status(session, run, RunStatus.DEPLOYING)
        await _commit_and_ping(session, run_id)

    from engine.agents.release import run_preview_release

    async def record(name: str, payload: dict) -> None:
        async with session_scope() as session:
            _emit(session, run_id, name, payload, agent=AgentRole.RELEASE_ENGINEER)
            await _commit_and_ping(session, run_id)

    try:
        deployment = await run_preview_release(
            ctx.ws,
            credentials,
            options=options,
            expected_sha=approved_sha,
            on_event=record,
        )
    except Exception as exc:
        message = _scrub(str(exc) or type(exc).__name__, credentials)
        await _teardown_after_error(run_id, credentials)
        credentials.clear()
        await _fail_deploy(run_id, f"preview deploy failed: {message}")
        return False
    credentials.clear()

    problem: str | None = None
    if deployment.status == "failed":
        problem = f"preview deploy failed: {_scrub(deployment.error or 'unknown error')}"
    elif deployment.source_sha and not approved_sha.startswith(deployment.source_sha):
        problem = "the deployed commit differs from the approved commit"
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.preview_deployment = deployment.model_dump(mode="json")
        if problem is None:
            run.deployment_status = "simulated" if deployment.status == "simulated" else "deployed"
            _set_run_status(session, run, RunStatus.EXECUTING)
        await _commit_and_ping(session, run_id)
    if problem is not None:
        await _teardown_preview(run_id)
        await _fail_deploy(run_id, problem)
        return False
    return True


async def _request_deploy_approval(
    ctx: _Exec, options: PreviewOptions, head: str, design_note: str
) -> bool:
    """Checkpoint the run in awaiting_deploy_approval and return without deploying."""
    run_id = ctx.run_id
    fake = get_settings().llm_fake
    ready, problems, notes = True, [], []
    try:
        from engine.agents.release import assess_release_readiness

        report = await assess_release_readiness(ctx.ws, options)
        ready, problems, notes = report.ready, list(report.problems), list(report.notes)
    except Exception as exc:
        ready, problems = False, [_scrub(f"readiness check failed: {exc}")]
    if not ready and not fake:
        await _fail_deploy(run_id, "preview is not ready: " + "; ".join(problems)[:280])
        return False

    usage = LlmUsage()
    async with _agent_model(run_id, AgentRole.RELEASE_ENGINEER):
        note = await write_readiness_note(
            ctx.request,
            design_note,
            options,
            ctx.ws,
            usage,
            _tool_observer(run_id, AgentRole.RELEASE_ENGINEER),
            _reasoning_observer(run_id, AgentRole.RELEASE_ENGINEER),
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _apply_usage(run, usage)
        _emit(
            session,
            run_id,
            "release.readiness",
            {
                "note": note,
                "ready": ready,
                "problems": [p[:200] for p in problems[:10]],
                "notes": [n[:200] for n in notes[:10]],
                "source_sha": head,
            },
            agent=AgentRole.RELEASE_ENGINEER,
        )
        _emit(
            session,
            run_id,
            "deploy.approval_requested",
            {
                "source_sha": head,
                "ttl_hours": options.ttl_hours,
                "mode": "simulated" if fake else "live",
            },
        )
        run.deployment_status = "awaiting_approval"
        _set_run_status(session, run, RunStatus.AWAITING_DEPLOY_APPROVAL)
        await _commit_and_ping(session, run_id)
    return False  # parked for the second human approval


async def _fail_deploy(run_id: uuid.UUID, error: str) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.deployment_status in ("awaiting_approval", "approved", "deploying"):
            run.deployment_status = "failed"
        _fail_run(session, run, error)
        await _commit_and_ping(session, run_id)


async def _teardown_preview(run_id: uuid.UUID) -> None:
    """Tear down the saved preview through the shared cleanup helper (best effort:
    on failure it keeps the record and a later sweep retries)."""
    from engine.agents.preview_cleanup import cleanup_run_preview

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.deployment_status in ("approved", "deploying"):
            run.deployment_status = "deployed"  # lets the cleanup helper claim it
        await _commit_and_ping(session, run_id)
    try:
        await cleanup_run_preview(run_id)
    except Exception:
        log.exception("preview.teardown_failed", run_id=str(run_id))


async def _teardown_after_error(run_id: uuid.UUID, credentials: dict[str, str]) -> None:
    """The deploy call raised before returning a record: remove whatever it created."""
    if get_settings().llm_fake or not credentials:
        return
    try:
        from engine.agents.release import teardown_preview_for_run

        await teardown_preview_for_run(run_id, credentials)
    except Exception:
        log.warning("preview.teardown_failed", run_id=str(run_id))


async def _stage_cloud_tests(ctx: _Exec) -> bool:
    """Judge the smoke evidence the release step collected against the live preview."""
    run_id = ctx.run_id
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if not preview_wanted(run):
            return True
        if not run.preview_deployment:
            _fail_run(session, run, "cloud tests cannot run: no preview deployment was recorded")
            await _commit_and_ping(session, run_id)
            return False
        deployment = PreviewDeployment.model_validate(run.preview_deployment)
        evidence = _smoke_evidence(deployment.smoke)
        simulated = deployment.status == "simulated"
        passed = simulated or (deployment.smoke is not None and deployment.smoke.passed)
        _emit(
            session,
            run_id,
            "cloud_tests.finished",
            {
                **evidence,
                "simulated": simulated,
                # An offline run reports no smoke result and is never failed for it.
                "passed": None if simulated else passed,
                "url": None if simulated else deployment.url,
            },
            agent=AgentRole.QA,
        )
        if passed and not simulated:
            run.deployment_status = "verified"
        await _commit_and_ping(session, run_id)
    if passed:
        return True
    await _teardown_preview(run_id)
    reason = evidence.get("error") or (
        "a smoke check failed" if deployment.smoke is not None else "no smoke tests ran"
    )
    await _fail_deploy(run_id, f"cloud smoke tests failed: {reason}")
    return False


_STAGE_HANDLERS = {
    StageName.DESIGN: _stage_design,
    StageName.BUILD: _stage_build,
    StageName.REVIEW: _stage_review,
    StageName.PRINCIPAL_REVIEW: _stage_principal_review,
    StageName.SANDBOX: _stage_sandbox,
    StageName.SECURITY: _stage_security,
    StageName.DEPENDENCY: _stage_dependency,
    StageName.PREVIEW_DEPLOY: _stage_preview_deploy,
    StageName.CLOUD_TESTS: _stage_cloud_tests,
    StageName.PUBLISH: _stage_publish,
    StageName.TEST_REPORT: _stage_test_report,
}


async def _execute_test_report(run_id: uuid.UUID, ws: Workspace) -> None:
    """One deterministic QA seat: sandbox only, no editing tools or publishing.

    A red test suite is a valid report. Infrastructure failures retry and can
    escalate classification, but never grant permission to edit the repo.
    """
    for attempt in range(1, 4):
        async with session_scope() as session:
            task = (
                (
                    await session.execute(
                        select(AgentTask)
                        .where(AgentTask.run_id == run_id)
                        .order_by(AgentTask.sequence)
                    )
                )
                .scalars()
                .first()
            )
            assert task is not None
            task_id = task.id
            task.status = TaskStatus.IN_PROGRESS
            task.attempts = attempt
            task.started_at = task.started_at or _now()
            _emit(
                session,
                run_id,
                "task.status_changed",
                {
                    "to": TaskStatus.IN_PROGRESS,
                    "title": task.title,
                },
                agent=AgentRole.QA,
                task_id=task_id,
            )
            await _commit_and_ping(session, run_id)
        try:
            result = await run_sandbox(ws.path, run_id)
        except Exception as exc:
            result = SandboxResult(
                "failed", "sandbox infrastructure error", str(exc)[:2000], None, None
            )
        await _emit_sandbox_run(run_id, result, attempt=attempt - 1)
        infrastructure_failure = result.status == "failed" and result.exit_code is None
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            task = await session.get(AgentTask, task_id)
            assert run is not None and task is not None
            run.test_report = {
                "status": result.status,
                "reason": result.reason,
                "exit_code": result.exit_code,
                "output": result.output[-4000:],
                "test_command": result.plan.test if result.plan else None,
                "scope": "repository test suite",
            }
            if infrastructure_failure and attempt < 3:
                task.status = TaskStatus.PENDING
                _emit(
                    session,
                    run_id,
                    "task.attempt_failed",
                    {
                        "attempt": attempt,
                        "error": result.reason,
                    },
                    agent=AgentRole.QA,
                    task_id=task_id,
                )
                if attempt == 2:
                    _escalate(session, run, "QA sandbox failed twice; continue with Standard retry")
                await _commit_and_ping(session, run_id)
                continue
            detail = result.reason or (result.plan.test if result.plan else "not run")
            task_result = f"Tests {result.status}: {detail}\n{result.output[-4000:]}"
            task.result = task_result
            task.finished_at = _now()
            task.status = TaskStatus.FAILED if infrastructure_failure else TaskStatus.DONE
            _emit(
                session,
                run_id,
                "tests.reported",
                run.test_report,
                agent=AgentRole.QA,
                task_id=task_id,
            )
            _emit(
                session,
                run_id,
                "task.status_changed",
                {
                    "to": task.status,
                    "result": task_result[:500],
                },
                agent=AgentRole.QA,
                task_id=task_id,
            )
            if infrastructure_failure:
                _fail_run(
                    session, run, f"sandbox could not run after three attempts: {result.reason}"
                )
            else:
                _set_run_status(session, run, RunStatus.COMPLETED)
                run.finished_at = _now()
                _emit(session, run_id, "run.finished", {"status": run.status, "error": None})
            await _commit_and_ping(session, run_id)
            return


async def _review(run_id: uuid.UUID, request: str, plan_summary: str, ws: Workspace) -> dict:
    usage = LlmUsage()
    async with _agent_model(run_id, AgentRole.REVIEWER):
        verdict = await review_run(
            request,
            plan_summary,
            ws,
            usage,
            _tool_observer(run_id, AgentRole.REVIEWER),
            _reasoning_observer(run_id, AgentRole.REVIEWER),
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _apply_usage(run, usage)
        _emit(
            session,
            run_id,
            "review.verdict",
            {
                "verdict": verdict["verdict"],
                "findings": [f["issue"][:300] for f in verdict["findings"]],
            },
            agent=AgentRole.REVIEWER,
        )
        await _commit_and_ping(session, run_id)
    return verdict


async def _publish(
    run_id: uuid.UUID,
    repo_url: str,
    default_branch: str,
    request: str,
    plan_summary: str,
    ws: Workspace,
) -> str | None:
    """Push the run branch and open the host's request: a GitHub pull request
    (env token), a GitLab merge request, or a Bitbucket pull request (the
    owner's encrypted connection either way). A repo on none of the hosts —
    or a scratch workspace — just pushes. Design note:
    docs/architecture/agents/SOURCE_HOSTS.md."""
    title = request.strip().splitlines()[0][:72]

    # GitLab/Bitbucket repos publish with the run owner's encrypted connection.
    host: tuple[str, dict] | None = None
    preview_markdown: str | None = None
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is not None:
            host = await host_connection(session, run.user_id, repo_url)
            if run.preview_deployment:
                # The saved deployment record holds no credentials; the release
                # module words the evidence (a simulated run is labelled as such).
                from engine.agents.release import format_deploy_evidence

                preview_markdown = format_deploy_evidence(
                    PreviewDeployment.model_validate(run.preview_deployment)
                )
    body = build_pull_request_body(plan_summary, run_id, preview_markdown)

    pushed = await push_branch(ws, push_credential(host))
    if not pushed:
        return None

    pr_url: str | None = None
    if host is not None and host[0] == IntegrationKind.GITLAB:
        pr_url = await gitlab.open_merge_request(
            host[1], repo_url, ws.branch, default_branch, title, body
        )
    elif host is not None and host[0] == IntegrationKind.BITBUCKET:
        pr_url = await bitbucket.open_pull_request(
            host[1], repo_url, ws.branch, default_branch, title, body
        )
    elif parse_github_repo(repo_url) is not None and get_settings().github_token:
        pr_url = await open_pull_request(repo_url, ws.branch, default_branch, title, body)

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        # Saved with the publish checkpoint, so a restart never opens a second request.
        run.pr_url = pr_url
        _mark_stage(session, run, StageName.PUBLISH)
        _emit(
            session,
            run_id,
            "branch.published",
            {"branch": ws.branch, "pr_url": pr_url},
        )
        await _commit_and_ping(session, run_id)
    return pr_url


async def _sandbox_gate(run_id: uuid.UUID, request: str, ws: Workspace) -> bool:
    """Run the workspace's tests in the Docker sandbox before publishing.

    Returns True when the run may proceed: tests passed, or the sandbox was
    skipped (Docker unavailable, disabled, or no recognized test setup — the
    reason lands on the timeline either way). When the tests fail, the QA agent
    fixes the code and the sandbox re-runs, up to QA_MAX_ATTEMPTS times; only
    then does the run fail, so no pull request opens with failing tests.
    Design notes: SANDBOX_EXECUTION.md, QA_AGENT.md.
    """
    result = await run_sandbox(ws.path, run_id)
    await _emit_sandbox_run(run_id, result, attempt=0)
    if result.status != "failed":
        return True  # passed, or skipped — there is no failure for QA to act on

    max_attempts = get_settings().qa_max_attempts
    for attempt in range(1, max_attempts + 1):
        await _run_qa_fix(run_id, request, ws, result.output, attempt, max_attempts)
        result = await run_sandbox(ws.path, run_id)
        await _emit_sandbox_run(run_id, result, attempt=attempt)
        if result.status != "failed":
            return True

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _fail_run(
            session,
            run,
            f"sandbox tests still failing after {max_attempts} QA attempt(s): {result.reason}",
        )
        await _commit_and_ping(session, run_id)
    return False


async def _emit_sandbox_run(run_id: uuid.UUID, result: SandboxResult, attempt: int) -> None:
    """Record one sandbox run on the timeline (attempt 0 is the first pass, then
    one per QA retry). Output is capped so a run can never bloat a single row."""
    async with session_scope() as session:
        _emit(
            session,
            run_id,
            "sandbox.run",
            {
                "attempt": attempt,
                "status": result.status,
                "reason": result.reason,
                "exit_code": result.exit_code,
                "image": result.plan.image if result.plan else None,
                "test_command": result.plan.test if result.plan else None,
                "output": result.output[-2000:],
            },
        )
        await _commit_and_ping(session, run_id)


async def _run_qa_fix(
    run_id: uuid.UUID, request: str, ws: Workspace, failure_output: str, attempt: int, total: int
) -> None:
    """The QA agent reads the sandbox failure and commits a fix in the workspace."""
    before = await run_git(ws.path, "rev-parse", "HEAD")
    usage = LlmUsage()
    async with _agent_model(run_id, AgentRole.QA):
        summary = await fix_failing_tests(
            request,
            failure_output,
            ws,
            usage,
            attempt,
            total,
            _tool_observer(run_id, AgentRole.QA),
            _reasoning_observer(run_id, AgentRole.QA),
        )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        if run.team_template == "complex" and before != await run_git(ws.path, "rev-parse", "HEAD"):
            run.stages_completed = [
                stage for stage in run.stages_completed if stage != StageName.PRINCIPAL_REVIEW
            ]
        _apply_usage(run, usage)
        _emit(
            session,
            run_id,
            "qa.attempt",
            {"attempt": attempt, "summary": summary[:500]},
            agent=AgentRole.QA,
        )
        await _commit_and_ping(session, run_id)


async def _security_gate(run_id: uuid.UUID, ws: Workspace) -> bool:
    """Scan what the run added for leaked secrets (ADR-0008 secrets hygiene).

    Returns True when the run may proceed to open its pull request. On a hit it
    records the redacted findings, fails the run, and returns False so no branch
    is pushed and no pull request opens. Design note: SECRETS_SCANNING.md.
    """
    diff = await run_git(ws.path, "diff", ws.base_sha)
    findings = scan_diff(diff)
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _emit(
            session,
            run_id,
            "security.scan",
            {
                "blocked": bool(findings),
                "total_findings": len(findings),
                # Cap what one timeline event stores — a pathological diff could
                # match thousands of times and bloat the row.
                "findings": [
                    {"rule": f.rule, "path": f.path, "line": f.line, "match": f.redacted}
                    for f in findings[:50]
                ],
            },
        )
        if findings:
            summary = ", ".join(f"{f.rule} in {f.path}:{f.line}" for f in findings[:5])
            _fail_run(session, run, f"secret scan blocked the pull request: {summary}")
        await _commit_and_ping(session, run_id)
    return not findings


async def _dependency_gate(run_id: uuid.UUID, ws: Workspace) -> bool:
    """Block a pull request that adds a known-vulnerable dependency.

    Sibling of the secrets gate: scans the run's added manifest lines against a
    curated advisory list and fails the run on a match, so no pull request opens
    with a known-vulnerable package. Design note: DEPENDENCY_SCANNING.md.
    """
    diff = await run_git(ws.path, "diff", ws.base_sha)
    findings = scan_dependency_diff(diff)
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        _emit(
            session,
            run_id,
            "dependency.scan",
            {
                "blocked": bool(findings),
                "total_findings": len(findings),
                "findings": [
                    {
                        "package": f.package,
                        "version": f.version,
                        "ecosystem": f.ecosystem,
                        "advisory": f.advisory_id,
                        "severity": f.severity,
                        "path": f.path,
                        "line": f.line,
                    }
                    for f in findings[:50]
                ],
            },
        )
        if findings:
            summary = ", ".join(f"{f.package} {f.version} ({f.advisory_id})" for f in findings[:5])
            _fail_run(session, run, f"dependency scan blocked the pull request: {summary}")
        await _commit_and_ping(session, run_id)
    return not findings


def _to_task_state(task: AgentTask) -> TaskState:
    return TaskState(
        id=str(task.id),
        sequence=task.sequence,
        role=task.role,
        title=task.title,
        description=task.description,
        status=task.status,
        depends_on=list(task.depends_on),
        attempts=task.attempts,
        result=task.result,
        level=task.level,
    )


def _make_task_executor(run_id: uuid.UUID, request: str, ws: Workspace, known_ids: set[str]):
    """Wraps the engineer agents with the task board's bookkeeping: statuses,
    timestamps, events, and the run's token/cost totals. After a task
    succeeds it reloads the board and reports what the agents changed
    through the task-board tools — new tasks and skips — so the supervisor
    can merge them (TASK_BOARD_TOOLS.md)."""

    async def _execute(task: TaskState) -> ExecutionOutcome:
        task_id = uuid.UUID(task["id"])
        async with session_scope() as session:
            row = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            assert row is not None and run is not None
            _check_budget(run)  # each attempt re-raises; the run fails with the reason
            row.status = TaskStatus.IN_PROGRESS
            row.attempts = task["attempts"]
            row.started_at = _now()
            _emit(
                session,
                run_id,
                "task.status_changed",
                {"from": TaskStatus.PENDING, "to": TaskStatus.IN_PROGRESS, "title": task["title"]},
                agent=task["role"],
                task_id=task_id,
            )
            await _commit_and_ping(session, run_id)

        usage = LlmUsage()
        try:
            async with _agent_model(run_id, task["role"], task_id, task.get("level")):
                result = await execute_task(
                    task,
                    request,
                    ws,
                    usage,
                    _tool_observer(run_id, task["role"], task_id),
                    _reasoning_observer(run_id, task["role"], task_id),
                )
        except Exception as exc:
            async with session_scope() as session:
                row = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                assert row is not None and run is not None
                row.status = TaskStatus.PENDING  # the supervisor decides retry vs fail
                _apply_usage(run, usage)
                if task["attempts"] >= 2:
                    _escalate(
                        session, run, "engineer failed twice; retry with Standard review pipeline"
                    )
                _emit(
                    session,
                    run_id,
                    "task.attempt_failed",
                    {
                        "attempt": task["attempts"],
                        "title": task["title"],
                        "error": str(exc)[:500],
                    },
                    agent=task["role"],
                    task_id=task_id,
                )
                await _commit_and_ping(session, run_id)
            raise

        async with session_scope() as session:
            row = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            assert row is not None and run is not None
            row.status = TaskStatus.DONE
            row.result = result
            row.finished_at = _now()
            _apply_usage(run, usage)
            _emit(
                session,
                run_id,
                "task.status_changed",
                {"from": TaskStatus.IN_PROGRESS, "to": TaskStatus.DONE, "result": result[:500]},
                agent=task["role"],
                task_id=task_id,
            )
            # What did the agents change on the board while working? New rows
            # (add_task) and fresh skips (update_task_status) go back to the
            # supervisor so scheduling sees them.
            rows = (
                (await session.execute(select(AgentTask).where(AgentTask.run_id == run_id)))
                .scalars()
                .all()
            )
            new_tasks = [_to_task_state(r) for r in rows if str(r.id) not in known_ids]
            if len(rows) > 2 or len({r.role for r in rows if r.status != TaskStatus.SKIPPED}) > 1:
                _escalate(
                    session, run, "Quick board needs more than two tasks or another specialist"
                )
            known_ids.update(str(r.id) for r in rows)
            skipped_ids = [str(r.id) for r in rows if r.status == TaskStatus.SKIPPED]
            await _commit_and_ping(session, run_id)
        return ExecutionOutcome(result, new_tasks=new_tasks, skipped_task_ids=skipped_ids)

    return _execute
