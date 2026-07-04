"""End-to-end tests for the runs API with stub agents.

httpx's ASGI transport waits for FastAPI background tasks, so by the time a
POST /v1/runs response arrives the whole stub run has already executed —
no polling loops needed here.
"""

import uuid

import pytest

from engine.agents import runner
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def instant_stub_agents(monkeypatch):
    monkeypatch.setattr(runner, "STUB_TASK_SECONDS", 0)


def _headers() -> tuple[dict[str, str], str]:
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    return auth_headers(user_id), user_id


async def _create_run(client, headers, request="Add a /status endpoint") -> dict:
    resp = await client.post(
        "/v1/runs", json={"request": request, "repository_url": REPO}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_run_executes_to_completed_with_tasks_and_events(client):
    headers, _ = _headers()
    created = await _create_run(client, headers)

    detail = (await client.get(f"/v1/runs/{created['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert detail["error"] is None
    assert detail["repository_url"] == REPO
    assert detail["plan"]["tasks"]  # the stub PM planned something
    assert len(detail["tasks"]) == 4
    assert all(t["status"] == "done" and t["result"] for t in detail["tasks"])
    # the spec task runs first, the devops task last (diamond dependencies)
    assert detail["tasks"][0]["role"] == "product_manager"
    assert detail["tasks"][-1]["role"] == "devops"

    events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert "plan.created" in types
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)


async def test_events_cursor_returns_only_new_events(client):
    headers, _ = _headers()
    created = await _create_run(client, headers)

    all_events = (await client.get(f"/v1/runs/{created['id']}/events", headers=headers)).json()
    cursor = all_events[2]["id"]
    newer = (
        await client.get(f"/v1/runs/{created['id']}/events?after={cursor}", headers=headers)
    ).json()
    assert [e["id"] for e in newer] == [e["id"] for e in all_events[3:]]

    beyond = (
        await client.get(
            f"/v1/runs/{created['id']}/events?after={all_events[-1]['id']}", headers=headers
        )
    ).json()
    assert beyond == []


async def test_runs_are_listed_newest_first_and_reuse_the_repository(client):
    headers, _ = _headers()
    first = await _create_run(client, headers, request="first request")
    second = await _create_run(client, headers, request="second request")

    runs = (await client.get("/v1/runs", headers=headers)).json()
    assert [r["id"] for r in runs] == [second["id"], first["id"]]
    assert {r["repository_url"] for r in runs} == {REPO}


async def test_runs_are_owner_scoped(client):
    owner_headers, _ = _headers()
    intruder_headers, _ = _headers()
    created = await _create_run(client, owner_headers)

    assert (await client.get("/v1/runs", headers=intruder_headers)).json() == []
    for path in (f"/v1/runs/{created['id']}", f"/v1/runs/{created['id']}/events"):
        assert (await client.get(path, headers=intruder_headers)).status_code == 404


async def test_create_run_rejects_bad_input(client):
    headers, _ = _headers()
    bad_request = await client.post(
        "/v1/runs", json={"request": "", "repository_url": REPO}, headers=headers
    )
    assert bad_request.status_code == 422
    bad_url = await client.post(
        "/v1/runs", json={"request": "hi", "repository_url": "x"}, headers=headers
    )
    assert bad_url.status_code == 422
