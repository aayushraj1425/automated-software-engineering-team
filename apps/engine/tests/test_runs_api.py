"""End-to-end tests for the runs API with stub agents and the approval gate.

httpx's ASGI transport waits for FastAPI background tasks, so by the time a
POST response arrives the background work (planning, or executing after an
approval) has already finished — no polling loops needed here.
"""

import uuid

import pytest

from engine.agents import runner
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def instant_stub_agents(monkeypatch):
    monkeypatch.setattr(runner, "STUB_TASK_SECONDS", 0)


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
    assert len(detail["tasks"]) == 4
    assert all(t["status"] == "pending" for t in detail["tasks"])


async def test_approved_run_executes_to_completed(client):
    headers = _headers()
    created = await _create_run(client, headers)

    decided = await _decide(client, headers, created["id"], approved=True)
    assert decided.status_code == 200

    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert all(t["status"] == "done" and t["result"] for t in detail["tasks"])
    assert detail["tasks"][0]["role"] == "product_manager"
    assert detail["tasks"][-1]["role"] == "devops"

    events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert "plan.created" in types
    assert "plan.approved" in types
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
