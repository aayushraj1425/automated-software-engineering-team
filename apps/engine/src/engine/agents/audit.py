"""Mirror agent tool calls into the audit log.

Every tool an agent invokes already lands on the run timeline as a
``tool.called`` event (``agent_events``), but those are run-scoped and cascade
away when the run is deleted (RUN_HISTORY_RETENTION.md). The ``audit_logs`` table
is the platform's general actor/action record — the same table that logs a chat
message — so mirroring tool calls into it puts "who did what" for the agents in
the one queryable place, keyed by actor and action, alongside every other
audited action.

The mirror row is written in the *same transaction* as the timeline event (no
extra round trip). The acting user reaches the write through ``audit_user_var``,
a context variable set at each run entrypoint beside ``provider_keys_var``.

Design note: docs/architecture/AUDIT_LOG.md.
"""

import contextvars
import uuid

from engine.db.models import AuditLog

# The action recorded for every agent tool call — the category, like
# "chat.message"; the specific tool and outcome live in the row's meta.
TOOL_CALL_ACTION = "tool.called"

# The owner of the run currently executing, set at each run entrypoint so a tool
# call is attributed to the person on whose behalf the agents act. "system" when
# unset — offline tooling, or a test that calls a tool directly.
audit_user_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "audit_user", default=None
)


def build_audit_log(
    run_id: uuid.UUID,
    agent: str | None,
    task_id: uuid.UUID | None,
    tool: str,
    args: dict[str, str],
    ok: bool,
    result_preview: str,
) -> AuditLog:
    """One audit row for a tool invocation, in the general audit-log shape: the
    acting user (from ``audit_user_var``), the ``tool.called`` action, the run as
    the target, and the tool/agent/outcome detail in ``meta``. The caller adds
    the row to its session and commits it alongside the timeline event."""
    return AuditLog(
        actor_id=audit_user_var.get() or "system",
        action=TOOL_CALL_ACTION,
        target=str(run_id),
        meta={
            "tool": tool,
            "agent": agent,
            "ok": ok,
            "task_id": str(task_id) if task_id else None,
            "args": args,
            "result": result_preview,
        },
    )
