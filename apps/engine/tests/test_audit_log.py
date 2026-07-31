"""Mirroring agent tool calls into the audit log. Design note:
docs/architecture/security/AUDIT_LOG.md."""

import uuid
from decimal import Decimal

from sqlalchemy import select

from engine.agents.audit import TOOL_CALL_ACTION, audit_user_var, build_audit_log
from engine.agents.runner import _tool_observer
from engine.db.enums import AgentRole
from engine.db.models import AgentRun, AuditLog, Repository
from engine.db.session import session_scope


async def _make_run(user_id: str = "user_test") -> uuid.UUID:
    """A persisted run so the observer's agent_events FK is satisfied — the
    observer writes the timeline event and the audit mirror together."""
    async with session_scope() as session:
        repo = Repository(owner_id=user_id, url="https://github.com/acme/demo")
        session.add(repo)
        await session.flush()
        run = AgentRun(
            user_id=user_id,
            repository_id=repo.id,
            request="Add a /status endpoint",
            max_cost_usd=Decimal("5"),
        )
        session.add(run)
        await session.commit()
        return run.id


def test_build_audit_log_uses_the_general_shape():
    token = audit_user_var.set("user_42")
    try:
        row = build_audit_log(
            run_id=(rid := uuid.uuid4()),
            agent=AgentRole.BACKEND,
            task_id=(tid := uuid.uuid4()),
            tool="read_file",
            args={"path": "app.py"},
            ok=True,
            result_preview="…",
        )
    finally:
        audit_user_var.reset(token)
    assert row.actor_id == "user_42"
    assert row.action == TOOL_CALL_ACTION
    assert row.target == str(rid)  # the run is the target
    assert row.meta["tool"] == "read_file"
    assert row.meta["agent"] == AgentRole.BACKEND
    assert row.meta["ok"] is True
    assert row.meta["task_id"] == str(tid)


def test_build_audit_log_actor_is_system_when_unset():
    # A tool called outside a run's context (offline tooling) is still recorded;
    # actor_id is NOT NULL, so it falls back to "system" rather than crashing.
    row = build_audit_log(uuid.uuid4(), None, None, "list_dir", {}, True, "")
    assert row.actor_id == "system"
    assert row.meta["task_id"] is None


async def test_observer_mirrors_a_tool_call(prepared_db):
    run_id = await _make_run()
    token = audit_user_var.set("user_test")
    try:
        record = _tool_observer(run_id, AgentRole.BACKEND)
        # A big content arg is summarized to its size, never stored verbatim.
        await record("write_file", {"path": "a.py", "content": "x" * 5000}, "wrote a.py")
    finally:
        audit_user_var.reset(token)

    async with session_scope() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.target == str(run_id))))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.action == TOOL_CALL_ACTION
    assert row.actor_id == "user_test"
    assert row.meta["tool"] == "write_file"
    assert row.meta["ok"] is True
    assert row.meta["args"]["content"] == "(5000 chars)"  # content sized, not stored


async def test_audit_rows_are_owner_scoped(prepared_db):
    """RLS: a user session reads only its own audit rows (actor_id), Postgres
    refuses the rest; the service context sees all (ROW_LEVEL_SECURITY.md)."""
    async with session_scope() as session:  # service context writes both
        session.add(build_audit_log(uuid.uuid4(), None, None, "read_file", {}, True, "ok"))
        # forge one owned by "alice" by writing it as her actor
        row = build_audit_log(uuid.uuid4(), None, None, "read_file", {}, True, "ok")
        row.actor_id = "alice"
        session.add(row)
        await session.commit()

    async with session_scope(user_id="alice") as session:  # alice sees only hers
        actors = set((await session.execute(select(AuditLog.actor_id))).scalars().all())
    assert actors == {"alice"}

    async with session_scope() as session:  # service sees both
        seen = set((await session.execute(select(AuditLog.actor_id))).scalars().all())
    assert {"alice", "system"} <= seen


async def test_observer_records_ok_false_for_an_error_result(prepared_db):
    run_id = await _make_run()
    record = _tool_observer(run_id, AgentRole.QA)
    await record("apply_patch", {"diff": "…"}, "ERROR: patch did not apply")

    async with session_scope() as session:
        row = (
            await session.execute(select(AuditLog).where(AuditLog.target == str(run_id)))
        ).scalar_one()
    assert row.meta["ok"] is False
    assert row.actor_id == "system"  # no run context set in this test
