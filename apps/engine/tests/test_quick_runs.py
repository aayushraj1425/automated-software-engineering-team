"""Quick runs exercise the real API, approval, workspaces, and supervisor."""

import os
import uuid

import pytest

from engine.agents import runner
from engine.agents.product_manager import _OFFLINE_PLAN
from engine.config import get_settings
from engine.db.models import AgentTask, IndexedFile
from engine.db.session import session_scope
from engine.sandbox.runner import SandboxPlan, SandboxResult
from engine.workspace.manager import run_git, workspaces_root
from tests.conftest import auth_headers

PLAN = SandboxPlan("python:3.12-slim", None, "python -m pytest -q")


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


async def create(client, request="Run the tests for login", **kwargs):
    headers = auth_headers("quick_" + uuid.uuid4().hex[:10])
    response = await client.post(
        "/v1/runs",
        headers=headers,
        json={
            "request": request,
            "repository_url": "https://github.com/acme/demo",
            **kwargs,
        },
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


@pytest.mark.parametrize(
    "status,reason,output,code",
    [
        ("passed", "", "4 passed", 0),
        ("failed", "tests failed", "test_login FAILED", 1),
        ("skipped", "no recognized test setup", "", None),
    ],
)
async def test_test_only_reports_without_writes_or_other_agents(
    client, monkeypatch, status, reason, output, code
):
    calls = []

    async def sandbox(path, run_id):
        calls.append(run_id)
        return SandboxResult(status, reason, output, code, PLAN)

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "test-only runs must never plan edits, fix tests, review, scan, or publish"
        )

    monkeypatch.setattr(runner, "run_sandbox", sandbox)
    for name in (
        "create_plan",
        "execute_task",
        "_run_qa_fix",
        "_review",
        "_security_gate",
        "_publish",
    ):
        monkeypatch.setattr(runner, name, forbidden)
    run_id, headers = await create(client)
    before = await detail(client, run_id, headers)
    assert before["status"] == "awaiting_approval" and not calls
    assert before["complexity"] == "quick" and before["test_only"]
    assert [task["role"] for task in before["tasks"]] == ["qa"]
    path = workspaces_root() / run_id
    head = await run_git(path, "rev-parse", "HEAD")
    after = await approve(client, run_id, headers)
    assert after["status"] == "completed" and after["pr_url"] is None
    assert len(calls) == 1
    assert after["test_report"]["status"] == status
    assert after["test_report"]["output"] == output
    assert (await run_git(path, "rev-parse", "HEAD")) == head
    assert not (await run_git(path, "status", "--porcelain")).strip()
    types = {event["type"] for event in await events(client, run_id, headers)}
    assert {"run.triaged", "team.assembled", "tests.reported"} <= types
    assert not {"model.selected", "review.verdict", "branch.published", "tool.called"} & types
    report = (await client.get(f"/v1/runs/{run_id}/report", headers=headers)).json()
    assert "## Test report" in report["markdown"]
    assert status in report["markdown"]


async def test_quick_change_keeps_scans_but_uses_one_engineer(client, tmp_path):
    # A real local origin makes branch publication testable without a host token.
    repo = tmp_path / "origin"
    repo.mkdir()
    (repo / "README.md").write_text("Fixture repository\n")
    await run_git(repo, "init", "-b", "main")
    await run_git(repo, "add", ".")
    await run_git(
        repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"
    )
    run_id, headers = await create(client, "Rename the login helper", repository_url=str(repo))
    before = await detail(client, run_id, headers)
    assert before["team_template"] == "quick" and len(before["tasks"]) == 1
    assert (await approve(client, run_id, headers))["status"] == "completed"
    timeline = await events(client, run_id, headers)
    types = {event["type"] for event in timeline}
    assert {"sandbox.run", "security.scan", "dependency.scan", "branch.published"} <= types
    assert "review.verdict" not in types
    assert {event["agent"] for event in timeline if event["type"] == "model.selected"} == {
        "backend"
    }


async def test_large_quick_plan_escalates_before_approval(client, monkeypatch):
    async def large(*args, **kwargs):
        return _OFFLINE_PLAN

    monkeypatch.setattr(runner, "create_plan", large)
    run_id, headers = await create(client, "Rename the login helper")
    before = await detail(client, run_id, headers)
    assert before["status"] == "awaiting_approval"
    assert before["complexity"] == "standard" and before["team_template"] == "standard"
    assert len(before["tasks"]) == 3
    assert (await approve(client, run_id, headers))["status"] == "completed"
    types = [event["type"] for event in await events(client, run_id, headers)]
    assert types.index("run.escalated") < types.index("plan.approved")
    assert "review.verdict" in types


async def test_two_engineer_failures_escalate_then_complete(client, monkeypatch):
    execute = runner.execute_task
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("temporary agent failure")
        return await execute(*args, **kwargs)

    monkeypatch.setattr(runner, "execute_task", flaky)
    run_id, headers = await create(client, "Rename the login helper")
    after = await approve(client, run_id, headers)
    assert after["status"] == "completed" and after["complexity"] == "standard"
    timeline = await events(client, run_id, headers)
    assert len([event for event in timeline if event["type"] == "run.escalated"]) == 1
    assert any(event["type"] == "review.verdict" for event in timeline)
    assert len(calls) == 3


async def test_quick_qa_repair_expands_team_and_gets_review(client, monkeypatch):
    results = iter(
        [
            SandboxResult("failed", "tests failed", "test_login FAILED", 1, PLAN),
            SandboxResult("passed", "", "4 passed", 0, PLAN),
            SandboxResult("passed", "", "4 passed", 0, PLAN),
        ]
    )

    async def sandbox(*args):
        return next(results)

    monkeypatch.setattr(runner, "run_sandbox", sandbox)
    run_id, headers = await create(client, "Rename the login helper")
    after = await approve(client, run_id, headers)
    assert after["status"] == "completed" and after["complexity"] == "standard"
    types = [event["type"] for event in await events(client, run_id, headers)]
    assert types.index("run.escalated") < types.index("review.verdict")
    assert "qa.attempt" in types and "security.scan" in types


async def test_new_tasks_escalate_quick_board(client, monkeypatch):
    execute = runner.execute_task
    added = False

    async def discovered(task, *args, **kwargs):
        nonlocal added
        if not added:
            added = True
            async with session_scope() as db:
                for sequence in (2, 3):
                    db.add(
                        AgentTask(
                            run_id=uuid.UUID(run_id),
                            sequence=sequence,
                            role="backend",
                            title=f"Discovered task {sequence}",
                            depends_on=[],
                        )
                    )
                await db.commit()
        return await execute(task, *args, **kwargs)

    monkeypatch.setattr(runner, "execute_task", discovered)
    run_id, headers = await create(client, "Rename the login helper")
    after = await approve(client, run_id, headers)
    assert after["status"] == "completed" and after["complexity"] == "standard"
    assert len(after["tasks"]) == 3 and all(task["status"] == "done" for task in after["tasks"])


async def test_quick_without_code_changes_does_not_publish(client, monkeypatch):
    async def no_change(*args, **kwargs):
        return "already correct"

    monkeypatch.setattr(runner, "execute_task", no_change)
    run_id, headers = await create(client, "Rename the login helper")
    assert (await approve(client, run_id, headers))["status"] == "completed"
    assert not any(
        event["type"] == "branch.published" for event in await events(client, run_id, headers)
    )


@pytest.mark.parametrize("permanent", [False, True])
async def test_test_infrastructure_retries_stay_read_only(client, monkeypatch, permanent):
    calls = []

    async def sandbox(*args):
        calls.append(1)
        if permanent or len(calls) < 3:
            raise RuntimeError("temporary docker connection error")
        return SandboxResult("passed", "", "4 passed", 0, PLAN)

    monkeypatch.setattr(runner, "run_sandbox", sandbox)
    run_id, headers = await create(client)
    after = await approve(client, run_id, headers)
    assert after["complexity"] == "standard" and after["test_only"]
    assert after["status"] == ("failed" if permanent else "completed")
    assert after["test_report"]["status"] == ("failed" if permanent else "passed")
    assert len(calls) == 3
    assert not any(
        event["type"] == "tool.called" for event in await events(client, run_id, headers)
    )


async def test_override_guards_and_owner_scope(client):
    run_id, headers = await create(client, "Rename the login helper")
    url = f"/v1/runs/{run_id}/triage"
    assert (
        await client.patch(url, headers=auth_headers("intruder"), json={"complexity": "standard"})
    ).status_code == 404
    assert (await client.patch(url, headers=headers, json={"complexity": "bad"})).status_code == 422
    assert (
        await client.patch(url, headers=headers, json={"complexity": "standard"})
    ).status_code == 200
    assert (await detail(client, run_id, headers))["team_template"] == "standard"
    await approve(client, run_id, headers)
    assert (
        await client.patch(url, headers=headers, json={"complexity": "quick"})
    ).status_code == 409
    run_id, headers = await create(client, "Add a dark mode toggle")
    assert (
        await client.patch(
            f"/v1/runs/{run_id}/triage", headers=headers, json={"complexity": "quick"}
        )
    ).status_code == 409


async def test_index_scope_integration(client):
    run_id, headers = await create(client, "Add login")
    from engine.db.models import AgentRun

    async with session_scope() as db:
        run = await db.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        for path in ("apps/api/login.py", "apps/web/login.ts"):
            db.add(IndexedFile(repository_id=run.repository_id, path=path, content_hash="a" * 64))
        await db.commit()
    response = await client.post(
        "/v1/runs",
        headers=headers,
        json={
            "request": "Rename login",
            "repository_url": "https://github.com/acme/demo",
        },
    )
    assert response.status_code == 201
    after = await detail(client, response.json()["id"], headers)
    assert after["complexity"] == "complex" and after["team_template"] == "complex"


@pytest.mark.skipif(os.getenv("ASEP_REAL_SANDBOX") != "1", reason="opt-in real Docker test")
async def test_real_sandbox_quick_report(client, monkeypatch, tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    (repo / "test_math.py").write_text("def test_sum():\n    assert 1 + 1 == 2\n")
    await run_git(repo, "init", "-b", "main")
    await run_git(repo, "add", ".")
    await run_git(
        repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"
    )
    monkeypatch.setattr(get_settings(), "sandbox_enabled", True)
    monkeypatch.setattr(get_settings(), "sandbox_required", True)
    run_id, headers = await create(client, repository_url=str(repo))
    after = await approve(client, run_id, headers)
    assert after["status"] == "completed", after
    assert after["test_report"]["status"] == "passed", after["test_report"]
    assert "1 passed" in after["test_report"]["output"]
