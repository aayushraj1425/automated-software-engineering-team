"""End-to-end tests for the runs API with offline agents and the approval gate.

LLM_FAKE=1 (set in conftest) makes the whole pipeline deterministic: planning
creates a scratch git workspace and a fixed three-task plan; after approval
the engineer agents write and commit real files through the jailed tools.
httpx's ASGI transport waits for FastAPI background tasks, so by the time a
POST response arrives the background work has already finished — no polling.
"""

import subprocess
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
    assert "tool.called" in types  # every tool invocation is audited
    assert "review.verdict" in types  # the Reviewer ran before completion
    assert types[-1] == "run.finished"
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)

    audited = [e for e in events if e["type"] == "tool.called"]
    assert {e["payload"]["tool"] for e in audited} == {"write_file", "git_commit"}
    assert all(e["payload"]["ok"] for e in audited)

    diff = (await client.get(f"/v1/runs/{created['id']}/diff", headers=headers)).json()
    assert ".asep/task-1.md" in diff["diff"]


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
    # a rejected run's workspace is deleted — and so is its diff
    assert not (workspaces_root() / created["id"]).exists()
    assert (await client.get(f"/v1/runs/{created['id']}/diff", headers=headers)).status_code == 404


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


async def test_exhausted_budget_fails_the_run_before_any_task_starts(client):
    from decimal import Decimal

    from engine.db.models import AgentRun
    from engine.db.session import session_scope

    headers = _headers()
    resp = await client.post(
        "/v1/runs",
        json={"request": "hi", "repository_url": REPO, "max_cost_usd": 0.05},
        headers=headers,
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Planning is free offline — spend the whole budget behind the scenes.
    async with session_scope() as session:
        run = await session.get(AgentRun, uuid.UUID(run_id))
        assert run is not None
        run.total_cost_usd = Decimal("0.05")
        await session.commit()

    await _decide(client, headers, run_id, approved=True)
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "failed"
    assert "budget" in detail["error"]
    assert all(t["status"] in ("failed", "skipped") for t in detail["tasks"])


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


# ── Workspace file browser (docs/architecture/WORKSPACE_PANELS.md) ──────────


async def _completed_run(client, headers) -> str:
    created = await _create_run(client, headers)
    resp = await _decide(client, headers, created["id"], True)
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    return created["id"]


async def test_files_lists_the_workspace(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    body = (await client.get(f"/v1/runs/{run_id}/files", headers=headers)).json()
    paths = [f["path"] for f in body["files"]]
    assert ".asep/task-1.md" in paths  # a file the offline engineers wrote
    assert body["truncated"] is False
    assert all(f["size"] >= 0 for f in body["files"])
    assert not any(p.startswith(".git/") for p in paths)  # .git is hidden


async def test_file_content_reads_a_file(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    resp = await client.get(
        f"/v1/runs/{run_id}/files/content", params={"path": ".asep/task-1.md"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == ".asep/task-1.md"
    assert body["content"].strip()
    assert body["truncated"] is False


async def test_file_content_rejects_a_jail_escape(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    resp = await client.get(
        f"/v1/runs/{run_id}/files/content",
        params={"path": "../../../../etc/passwd"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_file_content_missing_file_is_404(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    resp = await client.get(
        f"/v1/runs/{run_id}/files/content", params={"path": "does/not/exist.txt"}, headers=headers
    )
    assert resp.status_code == 404


async def test_files_404_when_the_workspace_is_gone(client):
    headers = _headers()
    created = await _create_run(client, headers)
    await _decide(client, headers, created["id"], False)  # rejecting deletes the workspace

    assert (await client.get(f"/v1/runs/{created['id']}/files", headers=headers)).status_code == 404


async def test_files_are_owner_scoped(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    intruder = _headers()
    assert (await client.get(f"/v1/runs/{run_id}/files", headers=intruder)).status_code == 404


# ── Editing the workspace + committing (finished runs only) ─────────────────


async def test_write_then_read_back_a_file(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    resp = await client.put(
        f"/v1/runs/{run_id}/files/content",
        json={"path": "notes.txt", "content": "hand-edited line\n"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["path"] == "notes.txt"

    read = await client.get(
        f"/v1/runs/{run_id}/files/content", params={"path": "notes.txt"}, headers=headers
    )
    assert read.json()["content"] == "hand-edited line\n"


async def test_write_is_jailed(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    resp = await client.put(
        f"/v1/runs/{run_id}/files/content",
        json={"path": "../escape.txt", "content": "nope"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_write_is_refused_before_the_run_finishes(client):
    headers = _headers()
    created = await _create_run(client, headers)  # left at awaiting_approval
    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "awaiting_approval"

    resp = await client.put(
        f"/v1/runs/{created['id']}/files/content",
        json={"path": "notes.txt", "content": "x"},
        headers=headers,
    )
    assert resp.status_code == 409  # the agent loop still owns the workspace


async def test_git_status_and_commit(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    await client.put(
        f"/v1/runs/{run_id}/files/content",
        json={"path": "notes.txt", "content": "a manual note\n"},
        headers=headers,
    )

    status = (await client.get(f"/v1/runs/{run_id}/git-status", headers=headers)).json()
    assert any(c["path"] == "notes.txt" for c in status["changes"])

    commit = await client.post(
        f"/v1/runs/{run_id}/commit", json={"message": "Add a manual note"}, headers=headers
    )
    assert commit.status_code == 200, commit.text
    assert commit.json()["sha"]

    # the tree is clean again after committing
    after = (await client.get(f"/v1/runs/{run_id}/git-status", headers=headers)).json()
    assert after["changes"] == []


async def test_commit_with_nothing_to_commit_is_400(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    resp = await client.post(
        f"/v1/runs/{run_id}/commit", json={"message": "Nothing changed"}, headers=headers
    )
    assert resp.status_code == 400


# ── Pushing the branch to the host (finished runs only) ─────────────────────


async def test_push_sends_the_branch_to_the_origin(client, tmp_path):
    """Commit by hand, push by hand — the origin ends up with the branch."""
    headers = _headers()
    run_id = await _completed_run(client, headers)

    # Give the scratch workspace a real (local) origin to push to.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    ws_path = workspaces_root() / run_id
    subprocess.run(
        ["git", "remote", "add", "origin", str(origin)],
        cwd=ws_path,
        check=True,
        capture_output=True,
    )

    resp = await client.post(f"/v1/runs/{run_id}/push", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pushed"] is True

    branches = subprocess.run(
        ["git", "branch", "--list", body["branch"]],
        cwd=origin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert body["branch"] in branches  # the origin really has the run branch

    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    pushes = [e for e in events if e["type"] == "branch.pushed"]
    assert len(pushes) == 1
    assert pushes[0]["payload"]["branch"] == body["branch"]


async def test_push_without_a_remote_is_400(client):
    """Offline scratch workspaces have no origin — a plain-language refusal."""
    headers = _headers()
    run_id = await _completed_run(client, headers)
    resp = await client.post(f"/v1/runs/{run_id}/push", headers=headers)
    assert resp.status_code == 400
    assert "no remote" in resp.json()["detail"]


async def test_push_is_refused_before_the_run_finishes(client):
    headers = _headers()
    created = await _create_run(client, headers)  # left at awaiting_approval
    resp = await client.post(f"/v1/runs/{created['id']}/push", headers=headers)
    assert resp.status_code == 409  # the agent loop still owns the workspace


async def test_write_is_owner_scoped(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    intruder = _headers()
    resp = await client.put(
        f"/v1/runs/{run_id}/files/content",
        json={"path": "notes.txt", "content": "x"},
        headers=intruder,
    )
    assert resp.status_code == 404
