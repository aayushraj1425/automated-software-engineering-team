"""End-to-end tests for the runs API with offline agents and the approval gate.

LLM_FAKE=1 (set in conftest) makes the whole pipeline deterministic: planning
creates a scratch git workspace and a fixed three-task plan; after approval
the engineer agents write and commit real files through the jailed tools.
httpx's ASGI transport waits for FastAPI background tasks, so by the time a
POST response arrives the background work has already finished — no polling.
"""

import uuid

import pytest

from engine.config import get_settings
from engine.workspace.manager import workspaces_root
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _create_run(client, headers, request="Add a /status endpoint") -> dict:
    resp = await client.post(
        "/v1/runs", json={"request": request, "repository_url": REPO}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _decide(client, headers, run_id: str, approved: bool):
    return await client.post(
        f"/v1/runs/{run_id}/decision", json={"approved": approved}, headers=headers
    )


async def test_run_plans_then_waits_for_approval(client):
    headers = _headers()
    created = await _create_run(client, headers)

    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["plan"]["tasks"]
    assert len(detail["tasks"]) == 3
    assert all(t["status"] == "pending" for t in detail["tasks"])
    # planning created the run's workspace (scratch repository in offline mode)
    assert (workspaces_root() / created["id"] / ".git").is_dir()


async def test_approved_run_executes_to_completed(client):
    headers = _headers()
    created = await _create_run(client, headers)

    decided = await _decide(client, headers, created["id"], approved=True)
    assert decided.status_code == 200

    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert all(t["status"] == "done" and t["result"] for t in detail["tasks"])
    assert [t["role"] for t in detail["tasks"]] == ["backend", "frontend", "devops"]
    # each offline engineer committed one file into the run's workspace
    ws = workspaces_root() / created["id"]
    assert (ws / ".asep" / "task-1.md").is_file()
    assert (ws / ".asep" / "task-3.md").is_file()

    events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert "plan.created" in types
    assert "plan.approved" in types
    assert "review.verdict" in types  # the Reviewer ran before completion
    assert types[-1] == "run.finished"
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)


async def test_rejected_run_is_cancelled_and_tasks_skipped(client):
    headers = _headers()
    created = await _create_run(client, headers)

    decided = await _decide(client, headers, created["id"], approved=False)
    assert decided.status_code == 200
    assert decided.json()["status"] == "cancelled"

    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "cancelled"
    assert all(t["status"] == "skipped" for t in detail["tasks"])
    events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    assert "plan.rejected" in [e["type"] for e in events]
    # a rejected run's workspace is deleted
    assert not (workspaces_root() / created["id"]).exists()


async def test_run_on_a_local_repository_pushes_the_branch(client, tmp_path):
    """Full pipeline against a real (local) repository: clone, plan, approve,
    engineer commits, review, and the run branch pushed back to the origin."""
    import subprocess

    origin = tmp_path / "origin"
    origin.mkdir()
    for args in (
        ["init", "--initial-branch=main"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@test.local"],
    ):
        subprocess.run(["git", *args], cwd=origin, check=True, capture_output=True)
    (origin / "README.md").write_text("# Demo\n")
    subprocess.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=origin, check=True, capture_output=True)

    headers = _headers()
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": str(origin)},
        headers=headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]
    await _decide(client, headers, run_id, approved=True)

    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert detail["pr_url"] is None  # local origin — nothing to open a PR on

    branches = subprocess.run(
        ["git", "branch", "--list", "asep/*"], cwd=origin, capture_output=True, text=True
    ).stdout
    assert f"asep/run-{uuid.UUID(run_id).hex[:8]}" in branches

    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    assert "branch.published" in [e["type"] for e in events]


async def test_decision_only_allowed_while_awaiting_approval(client):
    headers = _headers()
    created = await _create_run(client, headers)
    assert (await _decide(client, headers, created["id"], True)).status_code == 200
    # already executing/completed — a second decision must be refused
    assert (await _decide(client, headers, created["id"], True)).status_code == 409


async def test_events_cursor_returns_only_new_events(client):
    headers = _headers()
    created = await _create_run(client, headers)
    await _decide(client, headers, created["id"], approved=True)

    all_events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    cursor = all_events[2]["id"]
    newer = (
        await client.get(f"/v1/runs/{created['id']}/events?after={cursor}", headers=headers)
    ).json()
    assert [e["id"] for e in newer] == [e["id"] for e in all_events[3:]]


async def test_runs_are_listed_newest_first_and_reuse_the_repository(client):
    headers = _headers()
    first = await _create_run(client, headers, request="first request")
    second = await _create_run(client, headers, request="second request")

    runs = (await client.get("/v1/runs", headers=headers)).json()
    assert [r["id"] for r in runs] == [second["id"], first["id"]]
    assert {r["repository_url"] for r in runs} == {REPO}


async def test_runs_are_owner_scoped(client):
    owner = _headers()
    intruder = _headers()
    created = await _create_run(client, owner)

    assert (await client.get("/v1/runs", headers=intruder)).json() == []
    for path in (f"/v1/runs/{created['id']}", f"/v1/runs/{created['id']}/events"):
        assert (await client.get(path, headers=intruder)).status_code == 404
    assert (await _decide(client, intruder, created["id"], True)).status_code == 404


async def test_create_run_rejects_bad_input(client):
    headers = _headers()
    bad_request = await client.post(
        "/v1/runs", json={"request": "", "repository_url": REPO}, headers=headers
    )
    assert bad_request.status_code == 422
    bad_url = await client.post(
        "/v1/runs", json={"request": "hi", "repository_url": "x"}, headers=headers
    )
    assert bad_url.status_code == 422
