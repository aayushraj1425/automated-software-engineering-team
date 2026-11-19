import hashlib
import hmac
import json
import sys
import types
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from engine.agents import preview_cleanup
from engine.config import get_settings
from engine.db.models import AgentEvent, AgentRun, PreviewCredential
from engine.db.session import session_scope
from engine.deploy.contracts import PreviewDeployment


async def make_preview(*, simulated=True, expired=True, pr_url=None):
    run_id = uuid.uuid4()
    deployment = PreviewDeployment(
        run_id=run_id,
        namespace=f"asep-preview-{run_id.hex[:12]}",
        status="simulated" if simulated else "deployed",
        expires_at=datetime.now(UTC) + timedelta(hours=-1 if expired else 1),
    )
    async with session_scope() as db:
        db.add(
            AgentRun(
                id=run_id,
                user_id="preview_owner",
                org_id="preview_org",
                request="Deploy preview",
                status="completed",
                pr_url=pr_url,
                deployment_status=deployment.status,
                preview_deployment=deployment.model_dump(mode="json"),
            )
        )
        await db.commit()
    return run_id


async def test_expiry_cleans_simulated_preview_without_credentials(prepared_db):
    run_id = await make_preview()
    future = await make_preview(expired=False)
    assert await preview_cleanup.cleanup_expired_previews() == 1
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_status == "deleted"
        assert run.preview_deployment is not None
        assert run.preview_deployment["status"] == "deleted"
        run = await db.get(AgentRun, future)
        assert run is not None and run.deployment_status == "simulated"
    assert await preview_cleanup.cleanup_run_preview(run_id)


async def test_expired_verified_preview_is_also_cleaned(prepared_db):
    run_id = await make_preview()
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None
        run.deployment_status = "verified"
        await db.commit()
    assert await preview_cleanup.cleanup_expired_previews() >= 1
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_status == "deleted"


async def test_teardown_failure_is_redacted_and_retryable(prepared_db, monkeypatch):
    run_id = await make_preview(simulated=False, expired=False)
    credential = {"kubeconfig": "do-not-log-this-cloud-secret"}

    async def load(*args):
        return dict(credential)

    calls = []

    async def teardown(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("do-not-log-this-cloud-secret")

    module = types.ModuleType("engine.deploy.preview")
    module.__dict__["teardown_preview"] = teardown
    monkeypatch.setitem(sys.modules, "engine.deploy.preview", module)
    monkeypatch.setattr(preview_cleanup, "load_preview_credentials", load)
    assert not await preview_cleanup.cleanup_run_preview(run_id)
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_status == "cleanup_failed"
        events = list(
            (await db.execute(select(AgentEvent).where(AgentEvent.run_id == run_id))).scalars()
        )
        assert "do-not-log-this-cloud-secret" not in json.dumps([event.payload for event in events])
    assert await preview_cleanup.cleanup_expired_previews() >= 1
    assert len(calls) == 2


async def test_cluster_annotations_clean_previews_without_a_run_row(prepared_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_fake", False)
    async with session_scope() as db:
        db.add(
            PreviewCredential(org_id="orphan_org", created_by="owner", encrypted_credentials="stub")
        )
        await db.commit()
    handed_to_adapter = []

    async def load(*args):
        return {"kubeconfig": "private-credential"}

    async def sweep(credentials):
        assert credentials == {"kubeconfig": "private-credential"}
        handed_to_adapter.append(credentials)
        return types.SimpleNamespace(cleaned=["expired-orphan"], failed=[])

    monkeypatch.setattr(preview_cleanup, "load_preview_credentials", load)
    monkeypatch.setattr("engine.deploy.preview.sweep_expired_previews", sweep)
    assert await preview_cleanup.sweep_orphaned_previews() >= 1
    assert handed_to_adapter and all(value == {} for value in handed_to_adapter)


async def test_signed_merged_pull_request_cleans_preview(client, monkeypatch):
    run_id = await make_preview(expired=False, pr_url="https://github.com/acme/demo/pull/123")
    secret = "test-preview-webhook-secret"
    monkeypatch.setattr(get_settings(), "github_webhook_secret", secret)
    payload = json.dumps(
        {
            "action": "closed",
            "repository": {"full_name": "acme/demo"},
            "pull_request": {"number": 123, "merged": True},
        }
    ).encode()
    signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    response = await client.post(
        "/v1/webhooks/github",
        content=payload,
        headers={
            "x-github-event": "pull_request",
            "x-hub-signature-256": signature,
            "x-github-delivery": uuid.uuid4().hex,
        },
    )
    assert response.status_code == 202 and response.json()["status"] == "queued"
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_status == "deleted"
