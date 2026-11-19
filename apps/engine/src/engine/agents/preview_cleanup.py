"""Bounded, retryable cleanup for expired previews and merged pull requests."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import DateTime, cast, or_, select

from engine.config import get_settings
from engine.db.models import AgentEvent, AgentRun, PreviewCredential
from engine.db.session import session_scope
from engine.deploy.contracts import PreviewDeployment
from engine.events.bus import publish_run_ping
from engine.security.preview_credentials import load_preview_credentials

log = structlog.get_logger(__name__)


async def cleanup_run_preview(run_id: uuid.UUID) -> bool:
    """Claim one teardown; errors retain metadata and can be retried safely."""
    async with session_scope() as db:
        run = (
            await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        ).scalar_one_or_none()
        if run is None or not run.preview_deployment or run.deployment_status == "deleted":
            return True
        if run.deployment_status in ("approved", "deploying"):
            return False
        now = datetime.now(UTC)
        if run.deployment_status == "cleanup_pending" and run.updated_at > now - timedelta(
            minutes=10
        ):
            return False
        try:
            deployment = PreviewDeployment.model_validate(run.preview_deployment)
            if deployment.run_id != run_id:
                raise ValueError("preview identity mismatch")
            credentials = (
                {}
                if deployment.status == "simulated"
                else await load_preview_credentials(db, run.org_id)
            )
        except ValueError:
            run.deployment_status = "cleanup_failed"
            db.add(
                AgentEvent(
                    run_id=run_id,
                    type="deploy.cleanup_failed",
                    payload={"reason": "Preview metadata or credentials are unavailable"},
                )
            )
            await db.commit()
            return False
        run.deployment_status = "cleanup_pending"
        await db.commit()
    try:
        if deployment.status != "simulated":
            from engine.deploy.preview import teardown_preview

            await teardown_preview(deployment, credentials)
        succeeded = True
    except Exception:
        # Adapter output may contain authentication material. Never persist it.
        succeeded = False
    finally:
        credentials.clear()
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        if run is None:
            return succeeded
        run.deployment_status = "deleted" if succeeded else "cleanup_failed"
        if succeeded:
            run.preview_deployment = deployment.model_copy(update={"status": "deleted"}).model_dump(
                mode="json"
            )
        db.add(
            AgentEvent(
                run_id=run_id,
                type="deploy.cleaned_up" if succeeded else "deploy.cleanup_failed",
                payload={"namespace": deployment.namespace},
            )
        )
        await db.commit()
    await publish_run_ping(run_id)
    return succeeded


async def cleanup_expired_previews() -> int:
    async with session_scope() as db:
        rows = (
            await db.execute(
                select(AgentRun.id, AgentRun.preview_deployment, AgentRun.deployment_status)
                .where(
                    AgentRun.preview_deployment.is_not(None),
                    AgentRun.deployment_status.in_(
                        ["deployed", "verified", "simulated", "cleanup_failed", "cleanup_pending"]
                    ),
                    or_(
                        AgentRun.deployment_status.in_(["cleanup_failed", "cleanup_pending"]),
                        cast(
                            AgentRun.preview_deployment["expires_at"].astext,
                            DateTime(timezone=True),
                        )
                        <= datetime.now(UTC),
                    ),
                )
                .limit(500)
            )
        ).all()
    count = 0
    for run_id, payload, status in rows:
        try:
            deployment = PreviewDeployment.model_validate(payload)
            expires = deployment.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
        except ValueError:
            continue
        retry = status in ("cleanup_failed", "cleanup_pending")
        if (retry or expires <= datetime.now(UTC)) and await cleanup_run_preview(run_id):
            count += 1
    count += await sweep_orphaned_previews()
    return count


async def sweep_orphaned_previews() -> int:
    """Cluster annotations cover a crash before deployment metadata was persisted."""
    if get_settings().llm_fake:
        return 0
    from engine.deploy.preview import sweep_expired_previews

    async with session_scope() as db:
        org_ids = list((await db.execute(select(PreviewCredential.org_id))).scalars())
    cleaned = 0
    for org_id in org_ids:
        credentials: dict[str, str] = {}
        try:
            async with session_scope() as db:
                credentials = await load_preview_credentials(db, org_id)
            result = await sweep_expired_previews(credentials)
            cleaned += len(result.cleaned)
            if result.failed:
                log.warning("preview.sweep_incomplete", org_id=org_id, failed=len(result.failed))
        except Exception:
            log.warning("preview.sweep_failed", org_id=org_id)
        finally:
            credentials.clear()
    return cleaned


async def cleanup_pull_request_preview(pr_url: str) -> int:
    async with session_scope() as db:
        ids = list(
            (await db.execute(select(AgentRun.id).where(AgentRun.pr_url == pr_url))).scalars()
        )
    count = 0
    for run_id in ids:
        if await cleanup_run_preview(run_id):
            count += 1
    return count
