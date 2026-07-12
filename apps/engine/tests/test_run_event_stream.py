"""The run event stream: live timeline over SSE, resumable by cursor.

Postgres is the record and Redis only wakes the stream, so every test works
with or without a Redis server: a missing ping is covered by the heartbeat
(shrunk here so tests stay fast). Design note:
docs/architecture/RUN_EVENT_STREAMING.md.
"""

import asyncio
import json
import uuid

import pytest

import engine.events.bus as bus
from engine.config import get_settings
from engine.db.enums import RunStatus
from engine.db.models import AgentEvent, AgentRun
from engine.db.session import session_scope
from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))
    monkeypatch.setattr(bus, "HEARTBEAT_SECONDS", 0.2)


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


def _parse_stream(body: str) -> tuple[list[dict], dict | None]:
    """The stream's data payloads, and the `end` event's payload if present."""
    events: list[dict] = []
    end: dict | None = None
    for block in body.split("\n\n"):
        data_lines = [line for line in block.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        payload = json.loads(data_lines[0].removeprefix("data:"))
        if block.startswith("event: end"):
            end = payload
        else:
            events.append(payload)
    return events, end


async def _completed_run(client, headers) -> str:
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    run_id = resp.json()["id"]
    await client.post(f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers)
    return run_id


async def test_stream_replays_the_backlog_and_ends(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)

    resp = await client.get(f"/v1/runs/{run_id}/events/stream", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events, end = _parse_stream(resp.text)
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    ids = [e["id"] for e in events]
    assert ids == sorted(ids)  # the bigint identity id is the stream order
    assert end == {"status": "completed"}


async def test_stream_resumes_from_a_cursor(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    everything = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    middle = everything[len(everything) // 2]["id"]

    resp = await client.get(
        f"/v1/runs/{run_id}/events/stream", params={"after": middle}, headers=headers
    )
    events, end = _parse_stream(resp.text)
    assert events and all(e["id"] > middle for e in events)
    assert end == {"status": "completed"}


async def test_stream_honors_last_event_id_on_reconnect(client):
    headers = _headers()
    run_id = await _completed_run(client, headers)
    everything = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    last_seen = everything[-2]["id"]  # the reconnecting EventSource saw all but one

    resp = await client.get(
        f"/v1/runs/{run_id}/events/stream",
        headers={**headers, "Last-Event-ID": str(last_seen)},
    )
    events, end = _parse_stream(resp.text)
    assert [e["id"] for e in events] == [everything[-1]["id"]]
    assert end == {"status": "completed"}


async def test_stream_pushes_a_live_event_then_ends(client):
    """The point of the bus: an event that lands while the stream is open is
    pushed without a client round-trip (ping or heartbeat, either works)."""
    headers = _headers()
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": REPO},
        headers=headers,
    )
    run_id = resp.json()["id"]  # awaiting approval: the stream stays open

    async def finish_the_run_shortly() -> None:
        await asyncio.sleep(0.3)
        async with session_scope() as session:
            run = await session.get(AgentRun, uuid.UUID(run_id))
            assert run is not None
            session.add(AgentEvent(run_id=run.id, type="test.live", payload={}))
            run.status = RunStatus.CANCELLED
            await session.commit()
        await bus.publish_run_ping(uuid.UUID(run_id))

    mutation = asyncio.create_task(finish_the_run_shortly())
    stream = await asyncio.wait_for(
        client.get(f"/v1/runs/{run_id}/events/stream", headers=headers), timeout=15
    )
    await mutation

    events, end = _parse_stream(stream.text)
    assert "test.live" in [e["type"] for e in events]
    assert end == {"status": "cancelled"}


async def test_stream_is_owner_scoped(client):
    owner = _headers()
    run_id = await _completed_run(client, owner)
    stranger = _headers()
    resp = await client.get(f"/v1/runs/{run_id}/events/stream", headers=stranger)
    assert resp.status_code == 404


async def test_publish_never_raises_without_redis(monkeypatch):
    """The bus degrades, it never breaks a run: with Redis unreachable the
    ping is dropped and the subscription falls back to heartbeat pacing."""
    monkeypatch.setattr(get_settings(), "redis_url", "redis://localhost:1/0")
    monkeypatch.setattr(bus, "_client", None)
    monkeypatch.setattr(bus, "HEARTBEAT_SECONDS", 0.05)
    try:
        run_id = uuid.uuid4()
        await bus.publish_run_ping(run_id)  # must not raise
        async with bus.RunEventSubscription(run_id) as subscription:
            await asyncio.wait_for(subscription.wait(), timeout=5)  # heartbeat path
    finally:
        monkeypatch.setattr(bus, "_client", None)  # never leak the bad client
