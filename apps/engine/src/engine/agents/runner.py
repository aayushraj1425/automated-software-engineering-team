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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.engineer import execute_revision, execute_task
from engine.agents.loop import LlmUsage
from engine.agents.product_manager import create_plan
from engine.agents.qa import fix_failing_tests
from engine.agents.reviewer import APPROVE, REQUEST_CHANGES, review_run
from engine.agents.supervisor import TaskState, build_supervisor_graph
from engine.config import get_settings
from engine.db.enums import AgentRole, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask, Repository
from engine.db.session import session_scope
from engine.events.bus import publish_run_ping
from engine.github import open_pull_request, parse_github_repo
from engine.knowledge.capture import capture_run_memory
from engine.knowledge.recall import format_memories, recall_memories
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


def _check_budget(run: AgentRun) -> None:
    if run.max_cost_usd is not None and run.total_cost_usd >= run.max_cost_usd:
        raise BudgetExceeded(
            f"run budget of ${run.max_cost_usd} exhausted (spent ${run.total_cost_usd})"
        )


def _summarize_args(args: dict[str, Any]) -> dict[str, str]:
    # File contents don't belong in the timeline — record their size instead.
    return {
        key: f"({len(str(value))} chars)" if key == "content" else str(value)[:200]
        for key, value in args.items()
    }


def _tool_observer(run_id: uuid.UUID, agent: str | None, task_id: uuid.UUID | None = None):
    """Audit trail: one tool.called event per tool invocation (ADR-0008)."""

    async def _record(name: str, args: dict[str, Any], result: str) -> None:
        async with session_scope() as session:
            _emit(
                session,
                run_id,
                "tool.called",
                {
                    "tool": name,
                    "args": _summarize_args(args),
                    "ok": not result.startswith("ERROR:"),
                    "result": result[:200],
                },
                agent=agent,
                task_id=task_id,
            )
            await _commit_and_ping(session, run_id)

    return _record


async def plan_run(run_id: uuid.UUID) -> None:
    """Background entrypoint after POST /v1/runs: plan, then wait for approval."""
    await _guarded(_plan_run, run_id)
    # A run that failed during planning still leaves memory behind; a run
    # waiting for approval is not terminal, so capture does nothing.
    await capture_run_memory(run_id)


async def execute_tasks(run_id: uuid.UUID) -> None:
    """Background entrypoint after the human approves the plan."""
    await _guarded(_execute_tasks, run_id)
    # The run is terminal either way now — remember what happened
    # (KNOWLEDGE_AND_MEMORY.md); capture never raises.
    await capture_run_memory(run_id)


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


async def _plan_run(run_id: uuid.UUID) -> None:
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.QUEUED:
            return
        repo = await session.get(Repository, run.repository_id)
        assert repo is not None
        repo_url = repo.url
        repository_id = run.repository_id
        request = run.request
        run.started_at = _now()
        _emit(session, run_id, "run.started", {"request": run.request})
        _set_run_status(session, run, RunStatus.PLANNING)
        await _commit_and_ping(session, run_id)

    memory = await _recall_for_planning(run_id, repository_id, request)
    ws = await _open_workspace(run_id, repo_url)
    usage = LlmUsage()
    plan = await create_plan(
        request, ws, usage, _tool_observer(run_id, AgentRole.PRODUCT_MANAGER), memory=memory
    )

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.branch_name = ws.branch
        run.base_sha = ws.base_sha
        tasks: list[AgentTask] = []
        for sequence, item in enumerate(plan["tasks"], start=1):
            task = AgentTask(
                run_id=run_id,
                sequence=sequence,
                role=item["role"],
                title=item["title"],
                description=item["description"],
            )
            session.add(task)
            await session.flush()
            task.depends_on = [str(tasks[dep - 1].id) for dep in item["depends_on"]]
            tasks.append(task)
        run.plan = {"summary": plan["summary"], "tasks": [t.title for t in tasks]}
        _apply_usage(run, usage)
        _emit(session, run_id, "plan.created", run.plan, agent=AgentRole.PRODUCT_MANAGER)
        # Stop here: nothing executes until the human approves the plan.
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


async def _execute_tasks(run_id: uuid.UUID) -> None:
    # The human approved — reopen the workspace and let the Supervisor work.
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != RunStatus.EXECUTING:
            return
        repo = await session.get(Repository, run.repository_id)
        assert repo is not None
        repo_url = repo.url
        default_branch = repo.default_branch
        request = run.request
        plan_summary = str((run.plan or {}).get("summary", ""))
        branch = run.branch_name or ""
        base_sha = run.base_sha or ""
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

    ws = load_workspace(run_id, branch, base_sha)
    graph = build_supervisor_graph(_make_task_executor(run_id, request, ws))
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
            return
        _set_run_status(session, run, RunStatus.REVIEWING)
        await _commit_and_ping(session, run_id)

    verdict = await _review(run_id, request, plan_summary, ws)
    if verdict["verdict"] == REQUEST_CHANGES:
        # One revision round: each role fixes its own findings, then re-review.
        findings_by_role: dict[str, list[str]] = {}
        for finding in verdict["findings"]:
            findings_by_role.setdefault(finding["role"], []).append(finding["issue"])
        for role, issues in findings_by_role.items():
            usage = LlmUsage()
            summary = await execute_revision(
                role, issues, request, ws, usage, _tool_observer(run_id, role)
            )
            async with session_scope() as session:
                run = await session.get(AgentRun, run_id)
                assert run is not None
                _apply_usage(run, usage)
                _emit(
                    session,
                    run_id,
                    "review.revision",
                    {"role": role, "findings": len(issues), "summary": summary[:500]},
                    agent=role,
                )
                await _commit_and_ping(session, run_id)
        verdict = await _review(run_id, request, plan_summary, ws)

    if verdict["verdict"] != APPROVE:
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            assert run is not None
            _fail_run(session, run, "the reviewer did not approve the changes after one revision")
            await _commit_and_ping(session, run_id)
        return

    if not await _sandbox_gate(run_id, request, ws):
        return  # the tests did not pass; the run is already failed

    if not await _security_gate(run_id, ws):
        return  # a leaked secret blocks the pull request; the run is already failed

    if not await _dependency_gate(run_id, ws):
        return  # a known-vulnerable dependency blocks the PR; the run is already failed

    pr_url = await _publish(run_id, repo_url, default_branch, request, plan_summary, ws)

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        run.pr_url = pr_url
        _set_run_status(session, run, RunStatus.COMPLETED)
        run.finished_at = _now()
        _emit(session, run_id, "run.finished", {"status": run.status, "error": run.error})
        await _commit_and_ping(session, run_id)


async def _review(run_id: uuid.UUID, request: str, plan_summary: str, ws: Workspace) -> dict:
    usage = LlmUsage()
    verdict = await review_run(
        request, plan_summary, ws, usage, _tool_observer(run_id, AgentRole.REVIEWER)
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
    """Push the run branch; open the pull request when the repo is on GitHub
    and a token is configured. Scratch workspaces have nothing to push to."""
    pushed = await push_branch(ws)
    if not pushed:
        return None

    pr_url: str | None = None
    if parse_github_repo(repo_url) is not None and get_settings().github_token:
        title = request.strip().splitlines()[0][:72]
        body = (
            f"{plan_summary}\n\n"
            f"Opened by the ASEP agent team (run {run_id}).\n"
            "Review checklist: correctness, scope, security, consistency."
        )
        pr_url = await open_pull_request(repo_url, ws.branch, default_branch, title, body)

    async with session_scope() as session:
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
    usage = LlmUsage()
    summary = await fix_failing_tests(
        request, failure_output, ws, usage, attempt, total, _tool_observer(run_id, AgentRole.QA)
    )
    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
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
    )


def _make_task_executor(run_id: uuid.UUID, request: str, ws: Workspace):
    """Wraps the engineer agents with the task board's bookkeeping: statuses,
    timestamps, events, and the run's token/cost totals."""

    async def _execute(task: TaskState) -> str:
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
            result = await execute_task(
                task, request, ws, usage, _tool_observer(run_id, task["role"], task_id)
            )
        except Exception as exc:
            async with session_scope() as session:
                row = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                assert row is not None and run is not None
                row.status = TaskStatus.PENDING  # the supervisor decides retry vs fail
                _apply_usage(run, usage)
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
            await _commit_and_ping(session, run_id)
        return result

    return _execute
