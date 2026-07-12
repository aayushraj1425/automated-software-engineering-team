"""Tell the outside world a run finished.

Runs right after a run reaches a terminal state (beside capture_run_memory), so
it can never block or break the run. Loads the owner's enabled Slack connection,
posts the outcome, and records an `integration.notified` timeline event. A run
with no connection notifies nothing (no event); any failure is logged and
recorded, never raised. Design note: docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import uuid

import structlog

from engine.db.enums import IntegrationKind, RunStatus
from engine.db.models import AgentEvent, AgentRun
from engine.db.session import session_scope
from engine.events.bus import publish_run_ping
from engine.integrations import slack
from engine.integrations.connections import load_config

log = structlog.get_logger()

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED)


def _headline(request: str) -> str:
    return request.strip().splitlines()[0][:180]


def _message(run: AgentRun) -> str:
    headline = _headline(run.request)
    if run.status == RunStatus.COMPLETED:
        where = run.pr_url or "the branch was published without a pull request"
        return f"✅ ASEP run completed — {headline}\n{where}"
    return f"❌ ASEP run failed — {headline}\n{run.error or 'no reason recorded'}"


async def notify_run_outcome(run_id: uuid.UUID) -> None:
    """Post a terminal run's outcome to the owner's Slack connection, if any."""
    try:
        async with session_scope() as session:
            run = await session.get(AgentRun, run_id)
            if run is None or run.status not in _TERMINAL:
                return
            config = await load_config(session, run.user_id, IntegrationKind.SLACK)
            if config is None:
                return  # nothing connected — notify nothing, emit nothing

            payload: dict[str, object] = {"kind": IntegrationKind.SLACK}
            try:
                sent = await slack.post_message(config["webhook_url"], _message(run))
                payload |= {"ok": True, "dry_run": not sent}
            except slack.SlackError as exc:
                payload |= {"ok": False, "dry_run": False, "error": str(exc)[:200]}

            session.add(AgentEvent(run_id=run_id, type="integration.notified", payload=payload))
            await session.commit()
            await publish_run_ping(run_id)
    except Exception:
        # A notification is a byproduct; the run's own record is already saved.
        log.exception("integration.notify_failed", run_id=str(run_id))
