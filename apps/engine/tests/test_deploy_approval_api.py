import uuid

import pytest
from pydantic import ValidationError

from engine.api import runs
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun, Repository
from engine.db.session import session_scope
from engine.workspace.manager import create_scratch_workspace, run_git
from tests.conftest import auth_headers


def test_explicit_preview_request_requires_complex_team():
    body = {
        "request": "Ship preview",
        "repository_url": "https://github.com/acme/demo",
        "preview_requested": True,
    }
    assert runs.RunCreate.model_validate(body).complexity == "complex"
    for complexity in ("quick", "standard"):
        with pytest.raises(ValidationError, match="requires Complex"):
            runs.RunCreate.model_validate({**body, "complexity": complexity})


async def waiting_run(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))
    run_id = uuid.uuid4()
    ws = await create_scratch_workspace(run_id)
    async with session_scope() as db:
        repo = Repository(
            owner_id="deploy_owner", org_id="deploy_org", url="https://github.com/acme/demo"
        )
        db.add(repo)
        await db.flush()
        db.add(
            AgentRun(
                id=run_id,
                user_id="deploy_owner",
                org_id="deploy_org",
                repository_id=repo.id,
                request="Deploy a preview",
                status=RunStatus.AWAITING_DEPLOY_APPROVAL,
                branch_name=ws.branch,
                base_sha=ws.base_sha,
                deployment_status="awaiting_approval",
            )
        )
        await db.flush()
        db.add(
            AgentEvent(
                run_id=run_id, type="deploy.approval_requested", payload={"source_sha": ws.base_sha}
            )
        )
        await db.commit()
    return run_id, ws


async def test_second_approval_records_exact_commit_and_resumes_once(client, monkeypatch, tmp_path):
    run_id, ws = await waiting_run(monkeypatch, tmp_path)
    called = []

    async def execute(run_id):
        called.append(run_id)

    monkeypatch.setattr(runs, "dispatch_execute", execute)
    headers = auth_headers("deploy_owner", org_id="deploy_org")
    url = f"/v1/runs/{run_id}/deploy-decision"
    response = await client.post(url, headers=headers, json={"approved": True})
    assert response.status_code == 200, response.text
    assert called == [run_id]
    assert (await client.post(url, headers=headers, json={"approved": True})).status_code == 409
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_approved_at is not None
        assert run.deployment_approved_sha == (await run_git(ws.path, "rev-parse", "HEAD")).strip()
        assert run.deployment_approved_by == "deploy_owner"


@pytest.mark.parametrize("change", ["commit", "dirty"])
async def test_second_approval_cannot_deploy_changes_after_the_checks(
    client, monkeypatch, tmp_path, change
):
    run_id, ws = await waiting_run(monkeypatch, tmp_path)
    (ws.path / "late-change.txt").write_text("changed after checks", encoding="utf-8")
    if change == "commit":
        await run_git(ws.path, "add", "-A")
        await run_git(ws.path, "commit", "-m", "change after scans")
    response = await client.post(
        f"/v1/runs/{run_id}/deploy-decision",
        headers=auth_headers("deploy_owner", org_id="deploy_org"),
        json={"approved": True},
    )
    assert response.status_code == 409, response.text
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.deployment_approved_at is None


async def test_second_approval_refuses_other_member_and_can_reject(client, monkeypatch, tmp_path):
    run_id, _ = await waiting_run(monkeypatch, tmp_path)
    url = f"/v1/runs/{run_id}/deploy-decision"
    response = await client.post(
        url, headers=auth_headers("member", org_id="deploy_org"), json={"approved": True}
    )
    assert response.status_code == 403
    response = await client.post(
        url,
        headers=auth_headers("admin", org_id="deploy_org", org_role="admin"),
        json={"approved": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_live_approval_requires_configured_credentials(client, monkeypatch, tmp_path):
    run_id, _ = await waiting_run(monkeypatch, tmp_path)
    monkeypatch.setattr(get_settings(), "llm_fake", False)
    response = await client.post(
        f"/v1/runs/{run_id}/deploy-decision",
        headers=auth_headers("deploy_owner", org_id="deploy_org"),
        json={"approved": True},
    )
    assert response.status_code == 409
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None and run.status == RunStatus.AWAITING_DEPLOY_APPROVAL


@pytest.mark.parametrize("requested", [True, False])
async def test_rerun_preserves_preview_choices_but_requires_fresh_approvals(
    client, monkeypatch, tmp_path, requested
):
    run_id, _ = await waiting_run(monkeypatch, tmp_path)
    async with session_scope() as db:
        run = await db.get(AgentRun, run_id)
        assert run is not None
        run.complexity = "complex"
        run.preview_requested = requested
        run.preview_options = {"chart_path": "charts/app", "ttl_hours": 2}
        await db.commit()
    headers = auth_headers("deploy_owner", org_id="deploy_org")
    response = await client.post(f"/v1/runs/{run_id}/rerun", headers=headers)
    assert response.status_code == 201, response.text
    copied_id = response.json()["id"]
    copied = (await client.get(f"/v1/runs/{copied_id}", headers=headers)).json()
    assert copied["status"] == "awaiting_approval"
    assert copied["preview_requested"] is requested
    assert copied["preview_options"]["chart_path"] == "charts/app"
    async with session_scope() as db:
        run = await db.get(AgentRun, uuid.UUID(copied_id))
        assert run is not None
        assert run.deployment_approved_at is None and run.deployment_approved_sha is None
        assert run.preview_deployment is None and "preview_deploy" not in run.stages_completed
