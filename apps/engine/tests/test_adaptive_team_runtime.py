"""Adaptive team runtime: template stages, seat levels and models, the Principal's
design and review, the preview approval gate, deploy recovery and approval
preparation (docs/architecture/agents/ADAPTIVE_TEAM_RUNTIME.md).

Pure-logic tests need no database. The run tests drive the real API, runner and
recovery code offline (LLM_FAKE=1); the deploy adapter and its credentials are
stubbed behind their fixed signatures, so nothing here touches a cluster.
"""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from engine.agents import runner
from engine.agents.product_manager import PlanError, validate_plan
from engine.agents.pull_request import build_pull_request_body
from engine.agents.recovery import reset_interrupted_execution, reset_interrupted_planning
from engine.agents.registry import get_agent_spec
from engine.agents.teams import (
    get_team_template,
    preview_wanted,
    resolve_run_seat,
    template_name_for,
)
from engine.agents.teams_types import StageName
from engine.config import get_settings
from engine.db.enums import AgentRole, RunStatus, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask
from engine.db.session import session_scope
from engine.deploy.contracts import PreviewDeployment, SmokeResult
from engine.llm.catalog import ModelEntry, SeatLevel
from engine.llm.router import model_router, selection_observer_var
from engine.sandbox.runner import SandboxResult
from tests.conftest import auth_headers

SECRET = "SECRET-KUBECONFIG-CONTENT-0123456789"


# ── Pure logic ────────────────────────────────────────────────────────────────────────────────


def test_template_names_follow_complexity_and_keep_report_only_runs_read_only():
    assert template_name_for("quick", False) == "quick"
    assert template_name_for("standard", False) == "standard"
    assert template_name_for("complex", False) == "complex"
    assert template_name_for(None, False) == "standard"
    # A report-only request never gains write or publish stages from its label.
    for complexity in ("quick", "standard", "complex"):
        assert template_name_for(complexity, True) == "test_report"


def test_standard_template_keeps_todays_pipeline_order():
    template = get_team_template("standard")
    assert [s.value for s in template.stages] == [
        "plan",
        "build",
        "review",
        "sandbox",
        "security",
        "dependency",
        "publish",
    ]
    assert {seat.key for seat in template.seats} == {
        "product_manager:senior",
        "reviewer:senior",
        "qa:engineer",
    }


def test_complex_template_adds_principal_and_scans_before_any_deploy_or_publish():
    template = get_team_template("complex")
    stages = list(template.stages)
    assert stages[0] == StageName.DESIGN
    assert stages.index(StageName.REVIEW) < stages.index(StageName.PRINCIPAL_REVIEW)
    # Revisions happen in review, so the sandbox must come after both reviews.
    assert stages.index(StageName.PRINCIPAL_REVIEW) < stages.index(StageName.SANDBOX)
    for scan in (StageName.SECURITY, StageName.DEPENDENCY):
        assert stages.index(scan) < stages.index(StageName.PREVIEW_DEPLOY)
    assert stages.index(StageName.PREVIEW_DEPLOY) < stages.index(StageName.CLOUD_TESTS)
    assert stages.index(StageName.CLOUD_TESTS) < stages.index(StageName.PUBLISH)
    keys = {seat.key for seat in template.seats}
    assert {"principal_engineer:principal", "release_engineer:senior"} <= keys


def test_unknown_template_is_rejected():
    with pytest.raises(ValueError, match="unknown team template"):
        get_team_template("enormous")


def test_plan_levels_default_validate_and_collapse_for_quick():
    base = {"summary": "s", "tasks": [{"title": "t", "role": "backend", "depends_on": []}]}
    assert validate_plan(base)["tasks"][0]["level"] == "engineer"
    senior = {**base, "tasks": [{**base["tasks"][0], "level": "senior"}]}
    assert validate_plan(senior)["tasks"][0]["level"] == "senior"
    assert validate_plan(senior, quick=True)["tasks"][0]["level"] == "engineer"
    for bad in ("principal", "support", "god"):
        with pytest.raises(PlanError, match="level"):
            validate_plan({**base, "tasks": [{**base["tasks"][0], "level": bad}]})


@pytest.mark.parametrize(
    "requested,request_text,expected",
    [
        (True, "Add billing", True),
        (False, "Deploy the billing service to the cloud", False),
        (None, "Add billing, deploy it, test it on cloud", True),
        (None, "Create a preview environment for review", True),
        (None, "Migrate the database schema", False),
    ],
)
def test_preview_is_wanted_by_flag_or_by_the_words_of_the_request(
    requested, request_text, expected
):
    run = SimpleNamespace(preview_requested=requested, request=request_text)
    assert preview_wanted(run) is expected  # type: ignore[arg-type]


def test_registry_gives_levels_and_the_release_engineer_a_read_only_check():
    assert get_agent_spec(AgentRole.PRINCIPAL_ENGINEER).seat_level == SeatLevel.PRINCIPAL
    assert get_agent_spec(AgentRole.BACKEND).seat_level == SeatLevel.ENGINEER
    assert get_agent_spec(AgentRole.REVIEWER).seat_level == SeatLevel.SENIOR
    release = get_agent_spec(AgentRole.RELEASE_ENGINEER)
    assert "preview_check" in release.tools
    # Neither seat can edit the workspace.
    for role in (AgentRole.PRINCIPAL_ENGINEER, AgentRole.RELEASE_ENGINEER):
        assert not {"write_file", "apply_patch", "git_commit"} & set(get_agent_spec(role).tools)


def test_scrub_removes_credentials_and_bounds_errors():
    secrets = {"kubeconfig": f"line one\n  token: {SECRET}\nend"}
    text = runner._scrub(f"helm failed using token: {SECRET} and more", secrets)
    assert SECRET not in text and "[redacted]" in text
    assert len(runner._scrub("x" * 5000)) <= 300


def test_pull_request_body_carries_preview_evidence_before_the_checklist():
    run_id = uuid.uuid4()
    plain = build_pull_request_body("Plan", run_id)
    assert "Preview" not in plain
    body = build_pull_request_body(
        "Plan", run_id, "### Preview deployment\n\n- URL: https://p.test"
    )
    assert body.index("### Preview deployment") < body.index("## Definition of Done")
    assert body.index("## Summary") < body.index("### Preview deployment")


async def test_seat_resolution_applies_override_org_pin_and_open_source_opt_in(monkeypatch):
    calls = []

    def fake_resolve(level, overrides=None, budget=None, org_overrides=None, **kwargs):
        calls.append((level, overrides, budget, org_overrides, kwargs))
        return SimpleNamespace(model="m", level=level)

    monkeypatch.setattr(model_router, "resolve_seat", fake_resolve)

    class Session:
        def __init__(self, policy):
            self.policy = policy

        async def get(self, model, key):
            return self.policy

    policy = SimpleNamespace(
        level_pins={"engineer": "anthropic/org-pick"}, allow_open_source_auto=True
    )
    run = SimpleNamespace(
        org_id="org_1", model_overrides={"backend:engineer": "anthropic/human-pick"}
    )
    await resolve_run_seat(Session(policy), run, "backend", "engineer", 2.5)  # type: ignore[arg-type]
    await resolve_run_seat(Session(None), SimpleNamespace(org_id=None, model_overrides={}), "qa")  # type: ignore[arg-type]
    level, overrides, budget, org, kwargs = calls[0]
    assert level == SeatLevel.ENGINEER and budget == 2.5
    assert overrides == {"engineer": "anthropic/human-pick"}
    assert org == {"engineer": "anthropic/org-pick"}
    assert kwargs == {"allow_open_source_auto": True}
    # No policy: the keyword is not passed at all, so today's resolver is unchanged.
    assert calls[1][1] is None and calls[1][3] is None and calls[1][4] == {}


# ── Run helpers ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


async def create(client, request="Add a /status endpoint", **kwargs):
    headers = auth_headers("team_" + uuid.uuid4().hex[:10])
    response = await client.post(
        "/v1/runs",
        headers=headers,
        json={"request": request, "repository_url": "https://github.com/acme/demo", **kwargs},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], headers


async def detail(client, run_id, headers):
    return (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()


async def events(client, run_id, headers):
    return (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()


async def approve(client, run_id, headers):
    response = await client.post(
        f"/v1/runs/{run_id}/decision", headers=headers, json={"approved": True}
    )
    assert response.status_code == 200, response.text
    return await detail(client, run_id, headers)


async def parked_preview_run(client):
    """A Complex run with a requested preview, parked for the second approval."""
    pytest.importorskip("engine.agents.release")  # the Deploy workstream's module
    run_id, headers = await create(client, complexity="complex", preview_requested=True)
    parked = await approve(client, run_id, headers)
    assert parked["status"] == "awaiting_deploy_approval", parked
    return run_id, headers


async def head_of(run_id: str) -> str:
    from engine.workspace.manager import load_workspace, run_git

    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        ws = load_workspace(run.id, run.branch_name or "", run.base_sha or "")
    return (await run_git(ws.path, "rev-parse", "HEAD")).strip()


async def grant_approval(run_id: str, sha: str, resumed: RunStatus = RunStatus.EXECUTING) -> None:
    """What the deploy-decision endpoint records: who, when, which exact commit."""
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.deployment_approved_at = datetime.now(UTC)
        run.deployment_approved_by = run.user_id
        run.deployment_approved_sha = sha
        run.deployment_status = "approved"
        run.status = resumed
        await session.commit()


def live_preview(run_id: str, sha: str, passed: bool = True) -> PreviewDeployment:
    return PreviewDeployment(
        run_id=uuid.UUID(run_id),
        namespace="asep-preview-test",
        url="https://preview.example.test",
        status="deployed",
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        source_sha=sha,
        smoke=SmokeResult(
            passed=passed,
            checks=[{"path": "/healthz", "status": 200 if passed else 503, "ok": passed}],
            error=None if passed else "GET /healthz returned 503",
        ),
    )


class DeploySpy:
    """Stands in for the Deploy workstream's release functions (fixed signatures)."""

    def __init__(self, monkeypatch, deployment_for=None, error: Exception | None = None):
        release = pytest.importorskip("engine.agents.release")

        self.deploy_calls: list[dict] = []
        self.teardowns: list[PreviewDeployment] = []
        self.cleanup_for_run: list[uuid.UUID] = []
        self.deployment_for = deployment_for
        self.error = error

        async def run_preview_release(
            ws, credentials, *, options=None, expected_sha=None, on_event=None
        ):
            self.deploy_calls.append(
                {"sha": expected_sha, "credentials": dict(credentials), "run_id": ws.run_id}
            )
            if on_event is not None:
                await on_event("deploy.started", {"run_id": str(ws.run_id)})
            if self.error is not None:
                raise self.error
            assert self.deployment_for is not None
            deployment = self.deployment_for(str(ws.run_id), expected_sha)
            if on_event is not None:
                await on_event("deploy.finished", {"status": deployment.status})
            return deployment

        async def teardown_preview(deployment, credentials):
            self.teardowns.append(deployment)

        async def teardown_preview_for_run(run_id, credentials):
            self.cleanup_for_run.append(run_id)

        monkeypatch.setattr(release, "run_preview_release", run_preview_release)
        monkeypatch.setattr(release, "teardown_preview_for_run", teardown_preview_for_run)
        preview = pytest.importorskip("engine.deploy.preview")
        cleanup = pytest.importorskip("engine.agents.preview_cleanup")

        monkeypatch.setattr(preview, "teardown_preview", teardown_preview)

        async def credentials(db, org_id):
            return {"kubeconfig": SECRET}

        monkeypatch.setattr(cleanup, "load_preview_credentials", credentials)


# ── Standard and Complex runs ─────────────────────────────────────────────────────────────────


async def test_standard_run_records_levels_models_checkpoints_and_the_roster(client):
    run_id, headers = await create(client)
    planned = await detail(client, run_id, headers)
    assert planned["team_template"] == "standard" and planned["status"] == "awaiting_approval"
    assert all(task["level"] == "engineer" and task["model"] for task in planned["tasks"])
    keys = {seat["key"] for seat in planned["team"]}
    assert {"product_manager:senior", "reviewer:senior", "backend:engineer"} <= keys
    assert all(seat["model"] and seat["reason"] for seat in planned["team"])
    assert "plan" in planned["stages_completed"] and planned["design_note"] is None

    done = await approve(client, run_id, headers)
    assert done["status"] == "completed"
    stages = done["stages_completed"]
    assert stages == ["plan", "build", "review", "sandbox", "security", "dependency", "publish"]
    timeline = await events(client, run_id, headers)
    types = [event["type"] for event in timeline]
    assert "design.created" not in types and "deploy.skipped" not in types
    team = next(e for e in timeline if e["type"] == "team.assembled")
    assert team["payload"]["template"] == "standard"
    assert "reviewer" in team["payload"]["roles"] and team["payload"]["seats"]


async def test_complex_run_gets_a_design_note_senior_tasks_and_a_principal_review(client):
    run_id, headers = await create(client, complexity="complex")
    planned = await detail(client, run_id, headers)
    assert planned["team_template"] == "complex"
    assert planned["design_note"] and planned["stages_completed"][:2] == ["design", "plan"]
    levels = {task["role"]: task["level"] for task in planned["tasks"]}
    assert levels["devops"] == "senior" and levels["backend"] == "engineer"
    keys = {seat["key"] for seat in planned["team"]}
    assert {"principal_engineer:principal", "devops:senior", "backend:engineer"} <= keys
    assert {"release_engineer:senior"} <= keys
    timeline = await events(client, run_id, headers)
    types = [e["type"] for e in timeline]
    assert types.index("design.created") < types.index("plan.created")
    selected = [e for e in timeline if e["type"] == "model.selected"]
    assert any(e["agent"] == "principal_engineer" for e in selected)

    done = await approve(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    assert done["stages_completed"] == [
        "design",
        "plan",
        "build",
        "review",
        "principal_review",
        "sandbox",
        "security",
        "dependency",
        "preview_deploy",
        "cloud_tests",
        "publish",
    ]
    timeline = await events(client, run_id, headers)
    principal = [
        e for e in timeline if e["type"] == "review.verdict" and e["agent"] == "principal_engineer"
    ]
    assert principal and principal[0]["payload"]["verdict"] == "approve"
    # Nothing in the request asked for a cloud preview, so it is skipped, not approved.
    assert any(e["type"] == "deploy.skipped" for e in timeline)
    assert not any(e["type"].startswith("deploy.approval") for e in timeline)


async def test_roster_overrides_pin_a_seat_and_clearing_them_restores_auto(client, monkeypatch):
    def entry(name, strength, cost):
        return ModelEntry(
            id=f"anthropic/{name}",
            provider="anthropic",
            context_size=200_000,
            strength=strength,
            input_cost_per_million=cost,
            output_cost_per_million=cost * 5,
        )

    monkeypatch.setattr(
        get_settings(), "model_catalog", [entry("haiku-test", 3, 1.0), entry("sonnet-test", 4, 3.0)]
    )
    run_id, headers = await create(client)
    auto = await detail(client, run_id, headers)
    backend = next(seat for seat in auto["team"] if seat["key"] == "backend:engineer")
    assert backend["model"] == "anthropic/haiku-test" and backend["reason"].startswith("auto")

    url = f"/v1/runs/{run_id}/roster"
    pinned = await client.patch(
        url,
        headers=headers,
        json={"model_overrides": {"backend:engineer": "anthropic/sonnet-test"}},
    )
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    seat = next(seat for seat in body["team"] if seat["key"] == "backend:engineer")
    assert seat["model"] == "anthropic/sonnet-test" and "pinned" in seat["reason"]
    assert {t["model"] for t in body["tasks"] if t["role"] == "backend"} == {
        "anthropic/sonnet-test"
    }
    other = next(seat for seat in body["team"] if seat["key"] == "qa:engineer")
    assert other["model"] == "anthropic/haiku-test"

    cleared = await client.patch(url, headers=headers, json={"model_overrides": {}})
    seat = next(s for s in cleared.json()["team"] if s["key"] == "backend:engineer")
    assert seat["model"] == "anthropic/haiku-test"

    bad = await client.patch(
        url, headers=headers, json={"model_overrides": {"backend:engineer": "anthropic/nope"}}
    )
    assert bad.status_code == 422  # unknown model: nothing is saved
    assert (await detail(client, run_id, headers))["model_overrides"] == {}


async def test_task_level_and_override_choose_the_model_each_agent_runs_with(client, monkeypatch):
    def entry(name, strength, cost):
        return ModelEntry(
            id=f"anthropic/{name}",
            provider="anthropic",
            context_size=200_000,
            strength=strength,
            input_cost_per_million=cost,
            output_cost_per_million=cost,
        )

    monkeypatch.setattr(
        get_settings(),
        "model_catalog",
        [entry("small", 3, 1.0), entry("big", 4, 3.0), entry("best", 5, 9.0)],
    )
    run_id, headers = await create(
        client, complexity="complex", model_overrides={"devops:senior": "anthropic/best"}
    )
    planned = await detail(client, run_id, headers)
    models = {task["role"]: task["model"] for task in planned["tasks"]}
    assert models == {
        "backend": "anthropic/small",
        "frontend": "anthropic/small",
        "devops": "anthropic/best",
    }
    done = await approve(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    selected = {
        (e["agent"], e["task_id"]): e["payload"]["configured_model"]
        for e in await events(client, run_id, headers)
        if e["type"] == "model.selected" and e["task_id"]
    }
    by_task = {task["id"]: task for task in done["tasks"]}
    for (agent, task_id), configured in selected.items():
        assert configured == by_task[task_id]["model"], agent


# ── Preview approval, deploy and recovery ─────────────────────────────────────────────────────


async def test_preview_parks_for_a_second_approval_and_deploys_nothing(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    run_id, headers = await parked_preview_run(client)
    parked = await detail(client, run_id, headers)
    assert parked["deployment_status"] == "awaiting_approval" and parked["finished_at"] is None
    assert parked["preview_deployment"] is None and not spy.deploy_calls
    assert parked["stages_completed"][-1] == "dependency"  # scans finished before the pause
    timeline = await events(client, run_id, headers)
    types = [e["type"] for e in timeline]
    assert "release.readiness" in types and "deploy.approval_requested" in types
    assert not any(t in types for t in ("deploy.started", "deploy.finished", "branch.published"))
    request = next(e for e in timeline if e["type"] == "deploy.approval_requested")
    assert request["payload"]["source_sha"] == await head_of(run_id)


async def test_approved_preview_deploys_the_exact_commit_and_evidence_reaches_the_pr(
    client, monkeypatch
):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    bodies = []
    build_body = runner.build_pull_request_body

    def capture(plan_summary, run_id, preview=None):
        bodies.append(preview)
        return build_body(plan_summary, run_id, preview)

    monkeypatch.setattr(runner, "build_pull_request_body", capture)
    run_id, headers = await parked_preview_run(client)
    head = await head_of(run_id)
    response = await client.post(
        f"/v1/runs/{run_id}/deploy-decision", headers=headers, json={"approved": True}
    )
    assert response.status_code == 200, response.text
    done = await detail(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    assert [call["sha"] for call in spy.deploy_calls] == [head]
    assert done["deployment_status"] == "verified"
    assert done["preview_deployment"]["url"] == "https://preview.example.test"
    assert done["stages_completed"][-3:] == ["preview_deploy", "cloud_tests", "publish"]
    timeline = await events(client, run_id, headers)
    types = [e["type"] for e in timeline]
    assert types.index("deploy.approval_requested") < types.index("deploy.approved")
    assert types.index("deploy.approved") < types.index("deploy.started")
    assert types.index("deploy.finished") < types.index("cloud_tests.finished")
    smoke = next(e for e in timeline if e["type"] == "cloud_tests.finished")
    assert smoke["payload"]["passed"] is True and smoke["payload"]["checks"]
    assert len(bodies) == 1 and "https://preview.example.test" in bodies[0]
    assert "passed" in bodies[0]


async def test_simulated_preview_is_labelled_and_never_fails_the_offline_run(client, monkeypatch):
    bodies = []
    build_body = runner.build_pull_request_body

    def capture(plan_summary, run_id, preview=None):
        bodies.append(preview)
        return build_body(plan_summary, run_id, preview)

    monkeypatch.setattr(runner, "build_pull_request_body", capture)
    run_id, headers = await parked_preview_run(client)
    response = await client.post(
        f"/v1/runs/{run_id}/deploy-decision", headers=headers, json={"approved": True}
    )
    assert response.status_code == 200, response.text
    done = await detail(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    assert done["preview_deployment"]["status"] == "simulated"
    assert done["preview_deployment"]["url"] is None and done["deployment_status"] == "simulated"
    smoke = next(
        e for e in await events(client, run_id, headers) if e["type"] == "cloud_tests.finished"
    )
    assert smoke["payload"]["simulated"] is True and smoke["payload"]["passed"] is None
    # Where a body is built, it says SIMULATED rather than claiming live evidence.
    assert bodies and all("SIMULATED" in (body or "") for body in bodies)


async def test_a_commit_that_differs_from_the_approved_sha_is_never_deployed(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    run_id, headers = await parked_preview_run(client)
    head = await head_of(run_id)
    # Same seven-character prefix, different commit: the runner must compare the whole SHA.
    await grant_approval(run_id, head[:7] + "0" * (len(head) - 7))
    await runner.execute_tasks(uuid.UUID(run_id))
    failed = await detail(client, run_id, headers)
    assert failed["status"] == "failed" and "differs from the approved commit" in failed["error"]
    assert not spy.deploy_calls and failed["deployment_status"] == "failed"
    assert failed["preview_deployment"] is None


async def test_deploy_needs_every_approval_field(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    run_id, headers = await parked_preview_run(client)
    head = await head_of(run_id)
    await grant_approval(run_id, head)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.deployment_approved_by = None  # a status flip alone is not an approval
        await session.commit()
    await runner.execute_tasks(uuid.UUID(run_id))
    again = await detail(client, run_id, headers)
    assert again["status"] == "awaiting_deploy_approval" and not spy.deploy_calls


async def test_cloud_smoke_failure_tears_the_preview_down_and_blocks_the_pr(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha, passed=False))
    published = []

    async def no_publish(*args, **kwargs):
        published.append(args)

    monkeypatch.setattr(runner, "_publish", no_publish)
    run_id, headers = await parked_preview_run(client)
    await grant_approval(run_id, await head_of(run_id))
    await runner.execute_tasks(uuid.UUID(run_id))
    failed = await detail(client, run_id, headers)
    assert failed["status"] == "failed" and "cloud smoke tests failed" in failed["error"]
    assert "503" in failed["error"] and not published
    assert len(spy.teardowns) == 1 and failed["deployment_status"] == "deleted"
    smoke = next(
        e for e in await events(client, run_id, headers) if e["type"] == "cloud_tests.finished"
    )
    assert smoke["payload"]["passed"] is False


async def test_deploy_errors_and_events_never_contain_credentials(client, monkeypatch):
    spy = DeploySpy(monkeypatch, None, error=RuntimeError(f"helm failed: token {SECRET}"))
    credentials = pytest.importorskip("engine.security.preview_credentials")

    async def load(db, org_id):
        return {"kubeconfig": SECRET}

    monkeypatch.setattr(credentials, "load_preview_credentials", load)
    run_id, headers = await parked_preview_run(client)
    await grant_approval(run_id, await head_of(run_id))
    monkeypatch.setattr(get_settings(), "llm_fake", False)  # live mode loads credentials
    await runner._guarded(runner._execute_tasks, uuid.UUID(run_id))  # no memory capture
    monkeypatch.setattr(get_settings(), "llm_fake", True)
    failed = await detail(client, run_id, headers)
    assert failed["status"] == "failed" and "preview deploy failed" in failed["error"]
    assert spy.deploy_calls[0]["credentials"] == {"kubeconfig": SECRET}
    # Whatever the adapter created is removed, using the same credentials, outside any model.
    assert spy.cleanup_for_run == [uuid.UUID(run_id)]
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(AgentEvent.payload).where(AgentEvent.run_id == uuid.UUID(run_id))
            )
        ).scalars()
        stored = json.dumps(list(rows))
    blob = json.dumps(failed) + json.dumps(await events(client, run_id, headers)) + stored
    assert SECRET not in blob


async def test_missing_credentials_fail_before_any_deploy_starts(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    credentials = pytest.importorskip("engine.security.preview_credentials")

    async def missing(db, org_id):
        raise ValueError("No preview credential is configured for this organization")

    monkeypatch.setattr(credentials, "load_preview_credentials", missing)
    run_id, headers = await parked_preview_run(client)
    await grant_approval(run_id, await head_of(run_id))
    monkeypatch.setattr(get_settings(), "llm_fake", False)
    await runner._guarded(runner._execute_tasks, uuid.UUID(run_id))  # no memory capture
    monkeypatch.setattr(get_settings(), "llm_fake", True)
    failed = await detail(client, run_id, headers)
    assert failed["status"] == "failed" and "No preview credential" in failed["error"]
    assert not spy.deploy_calls and failed["deployment_status"] == "failed"
    types = {e["type"] for e in await events(client, run_id, headers)}
    assert "deploy.started" not in types


async def test_a_run_recovered_from_deploying_does_not_deploy_twice(client, monkeypatch):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    run_id, headers = await parked_preview_run(client)
    head = await head_of(run_id)
    await grant_approval(run_id, head, RunStatus.DEPLOYING)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        # The previous process saved the finished deployment, then died.
        run.preview_deployment = live_preview(run_id, head).model_dump(mode="json")
        run.deployment_status = "deployed"
        await session.commit()
    assert await reset_interrupted_execution(uuid.UUID(run_id))
    await runner.execute_tasks(uuid.UUID(run_id))
    done = await detail(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    assert not spy.deploy_calls
    types = [e["type"] for e in await events(client, run_id, headers)]
    assert "run.recovered" in types


async def test_a_run_recovered_mid_deploy_redeploys_once_with_its_saved_approval(
    client, monkeypatch
):
    spy = DeploySpy(monkeypatch, lambda run_id, sha: live_preview(run_id, sha))
    run_id, headers = await parked_preview_run(client)
    head = await head_of(run_id)
    await grant_approval(run_id, head, RunStatus.DEPLOYING)
    assert await reset_interrupted_execution(uuid.UUID(run_id))
    await runner.execute_tasks(uuid.UUID(run_id))
    assert (await detail(client, run_id, headers))["status"] == "completed"
    assert [call["sha"] for call in spy.deploy_calls] == [head]


async def test_a_run_waiting_for_deploy_approval_is_not_touched_by_recovery(client):
    run_id, headers = await parked_preview_run(client)
    assert not await reset_interrupted_execution(uuid.UUID(run_id))
    assert (await detail(client, run_id, headers))["status"] == "awaiting_deploy_approval"


async def test_a_second_publish_never_opens_another_request(client, monkeypatch):
    opened = []

    async def spy_publish(*args, **kwargs):
        opened.append(1)
        return "https://example.test/pr/1"

    monkeypatch.setattr(runner, "_publish", spy_publish)
    run_id, headers = await create(client)
    await approve(client, run_id, headers)
    assert len(opened) == 1
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.pr_url = "https://example.test/pr/1"
        run.stages_completed = [s for s in run.stages_completed if s != "publish"]
        run.status = RunStatus.EXECUTING
        await session.commit()
    await runner.execute_tasks(uuid.UUID(run_id))
    assert len(opened) == 1  # the saved pr_url wins


# ── Approval preparation after a complexity change ────────────────────────────────────────────


async def test_prepare_approval_team_adds_a_design_and_keeps_the_human_edited_board(client):
    run_id, headers = await create(client)
    planned = await detail(client, run_id, headers)
    first = planned["tasks"][0]
    edit = await client.put(
        f"/v1/runs/{run_id}/plan",
        headers=headers,
        json={"tasks": [{"id": first["id"], "title": "Human renamed this task"}]},
    )
    assert edit.status_code == 200, edit.text
    before = await detail(client, run_id, headers)
    assert before["design_note"] is None

    # What the API does after raising complexity: park the run in PLANNING.
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.complexity = "complex"
        run.team_template = "complex"
        run.status = RunStatus.PLANNING
        await session.commit()
    await runner.prepare_approval_team(uuid.UUID(run_id))

    after = await detail(client, run_id, headers)
    assert after["status"] == "awaiting_approval" and after["design_note"]
    assert [(t["id"], t["title"], t["description"]) for t in after["tasks"]] == [
        (t["id"], t["title"], t["description"]) for t in before["tasks"]
    ]
    assert after["tasks"][0]["title"] == "Human renamed this task"
    assert "principal_engineer:principal" in {seat["key"] for seat in after["team"]}
    assert "design" in after["stages_completed"]
    timeline = await events(client, run_id, headers)
    assembled = [e for e in timeline if e["type"] == "team.assembled"][-1]
    assert assembled["payload"]["template"] == "complex" and assembled["payload"]["reason"]
    assert any(e["type"] == "design.created" for e in timeline)

    done = await approve(client, run_id, headers)
    assert done["status"] == "completed", done["error"]
    assert "principal_review" in done["stages_completed"]


async def test_prepare_approval_team_without_a_design_only_rebuilds_the_roster(client):
    run_id, headers = await create(client, complexity="complex")
    before = await detail(client, run_id, headers)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.status = RunStatus.PLANNING
        run.team = []
        await session.commit()
    await runner.prepare_approval_team(uuid.UUID(run_id))
    after = await detail(client, run_id, headers)
    assert after["status"] == "awaiting_approval" and after["design_note"] == before["design_note"]
    assert {s["key"] for s in after["team"]} == {s["key"] for s in before["team"]}
    created = [e for e in await events(client, run_id, headers) if e["type"] == "design.created"]
    assert len(created) == 1  # not written twice


async def test_prepare_approval_team_failure_fails_the_run_through_the_guard(client, monkeypatch):
    run_id, headers = await create(client)

    async def broken(*args, **kwargs):
        raise RuntimeError("principal unavailable")

    monkeypatch.setattr(runner, "write_design_note", broken)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.complexity = "complex"
        run.team_template = "complex"
        run.status = RunStatus.PLANNING
        await session.commit()
    await runner.prepare_approval_team(uuid.UUID(run_id))
    failed = await detail(client, run_id, headers)
    assert failed["status"] == "failed" and "principal unavailable" in failed["error"]


async def test_prepare_approval_team_ignores_runs_that_are_not_parked_for_it(client):
    run_id, headers = await create(client)
    before = await detail(client, run_id, headers)
    await runner.prepare_approval_team(uuid.UUID(run_id))  # awaiting approval: stale call
    assert await detail(client, run_id, headers) == before


async def test_recovery_never_discards_a_planned_run_parked_in_planning(client):
    run_id, headers = await create(client)
    before = await detail(client, run_id, headers)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        # Raised to Complex after planning, design note not written yet.
        run.complexity = "complex"
        run.team_template = "complex"
        run.status = RunStatus.PLANNING
        await session.commit()
    assert not await reset_interrupted_planning(uuid.UUID(run_id), include_queued=True)
    async with session_scope() as session:
        tasks = (
            (await session.execute(select(AgentTask).where(AgentTask.run_id == uuid.UUID(run_id))))
            .scalars()
            .all()
        )
    assert len(tasks) == len(before["tasks"])


async def test_startup_recovery_finishes_approval_preparation_instead_of_replanning(client):
    from engine.agents.recovery import recover_interrupted_runs

    run_id, headers = await create(client)
    before = await detail(client, run_id, headers)
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.complexity = "complex"
        run.team_template = "complex"
        run.status = RunStatus.PLANNING
        await session.commit()
    recovered = await recover_interrupted_runs()
    assert uuid.UUID(run_id) in recovered
    after = await detail(client, run_id, headers)
    assert after["status"] == "awaiting_approval" and after["design_note"]
    assert [t["id"] for t in after["tasks"]] == [t["id"] for t in before["tasks"]]


async def test_fallback_model_history_survives_roster_reassembly(client):
    run_id, headers = await create(client)
    planned = await detail(client, run_id, headers)
    task = planned["tasks"][0]
    task_id = uuid.UUID(task["id"])
    run_uuid = uuid.UUID(run_id)
    async with runner._agent_model(run_uuid, task["role"], task_id, task["level"]) as choice:
        observer = selection_observer_var.get()
        assert observer is not None
        await observer(
            replace(choice, model="anthropic/fallback-for-history", reason="retry fallback")
        )
    async with session_scope() as session:
        row = await session.get(AgentTask, task_id)
        run = await session.get(AgentRun, run_uuid)
        assert row is not None and run is not None
        assert row.model == "anthropic/fallback-for-history"
        assert any(seat["model"] == row.model for seat in run.team)
        row.status = TaskStatus.DONE
        await runner.assemble_run_team(session, run)
        assert row.model == "anthropic/fallback-for-history"


async def test_quick_override_uses_the_single_remaining_engineer_seat(client):
    run_id, headers = await create(client, complexity="standard")
    planned = await detail(client, run_id, headers)
    response = await client.put(
        f"/v1/runs/{run_id}/plan",
        headers=headers,
        json={
            "tasks": [
                {"id": task["id"], "title": task["title"], "drop": task["role"] != "frontend"}
                for task in planned["tasks"]
            ]
        },
    )
    assert response.status_code == 200, response.text
    response = await client.patch(
        f"/v1/runs/{run_id}/triage", headers=headers, json={"complexity": "quick"}
    )
    assert response.status_code == 200, response.text
    quick = await detail(client, run_id, headers)
    assert len(quick["team"]) == 1 and quick["team"][0]["role"] == "frontend"


async def test_principal_reviews_the_final_qa_repair_commit(client, monkeypatch):
    checked_heads = []
    calls = 0

    async def principal(request, summary, design, ws, *args):
        checked_heads.append(await runner.run_git(ws.path, "rev-parse", "HEAD"))
        return {"verdict": "approve", "findings": []}

    async def sandbox(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SandboxResult("failed", "tests failed", "test failure", 1, None)
        return SandboxResult("passed", "", "tests passed", 0, None)

    monkeypatch.setattr(runner, "review_against_design", principal)
    monkeypatch.setattr(runner, "run_sandbox", sandbox)
    run_id, headers = await create(client, complexity="complex", preview_requested=False)
    done = await approve(client, run_id, headers)
    assert done["status"] == "completed", done.get("error")
    assert len(checked_heads) == 2 and checked_heads[0] != checked_heads[1]
    assert checked_heads[-1] == await head_of(run_id)
