"""Knowledge & Memory: the store, automatic capture, and recall into planning.

LLM_FAKE=1 (set in conftest) keeps everything offline: embeddings are
deterministic and the run pipeline is the fixed three-task plan, so a whole
run can complete inside a test and leave real memories behind.
Design note: docs/architecture/KNOWLEDGE_AND_MEMORY.md.
"""

import uuid

import pytest

from engine.config import get_settings
from engine.knowledge.recall import RecalledMemory, format_memories
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


def _repo_url() -> str:
    return f"https://github.com/acme/demo-{uuid.uuid4().hex[:8]}"


async def _create_repo(client, headers, url: str | None = None) -> str:
    resp = await client.post("/v1/repositories", json={"url": url or _repo_url()}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_note(client, headers, repo_id: str, **body) -> dict:
    body.setdefault("kind", "note")
    body.setdefault("title", "Deploys happen on Fridays")
    body.setdefault("content", "The team ships to production every Friday afternoon.")
    resp = await client.post(f"/v1/repositories/{repo_id}/knowledge", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _knowledge(client, headers, repo_id: str, q: str | None = None) -> list[dict]:
    params = {"q": q} if q else None
    resp = await client.get(f"/v1/repositories/{repo_id}/knowledge", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── The store: write, list, search, delete ──────────────────────────────────


async def test_note_roundtrip_newest_first(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    await _add_note(client, headers, repo_id, title="First memory")
    await _add_note(client, headers, repo_id, title="Second memory")

    listed = await _knowledge(client, headers, repo_id)
    assert [item["title"] for item in listed] == ["Second memory", "First memory"]
    assert all(item["kind"] == "note" and item["created_by"] for item in listed)


async def test_search_ranks_the_matching_memory_first(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    await _add_note(client, headers, repo_id, title="Unrelated", content="Nothing special here.")
    await _add_note(
        client,
        headers,
        repo_id,
        kind="preference",
        title="Database naming",
        content="Table names are always plural snake_case, like agent_runs.",
    )

    found = await _knowledge(client, headers, repo_id, q="snake_case table naming")
    assert found, "search returned nothing"
    assert found[0]["title"] == "Database naming"
    assert found[0]["score"] is not None


async def test_blank_note_is_rejected(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    resp = await client.post(
        f"/v1/repositories/{repo_id}/knowledge",
        json={"title": "   ", "content": "something"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_memory_is_owner_scoped(client):
    owner = _headers()
    repo_id = await _create_repo(client, owner)
    stranger = _headers()
    resp = await client.get(f"/v1/repositories/{repo_id}/knowledge", headers=stranger)
    assert resp.status_code == 404


async def test_delete_removes_the_memory(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    item = await _add_note(client, headers, repo_id)

    resp = await client.delete(
        f"/v1/repositories/{repo_id}/knowledge/{item['id']}", headers=headers
    )
    assert resp.status_code == 204
    assert await _knowledge(client, headers, repo_id) == []


# ── Automatic capture: runs write their own history ─────────────────────────


async def _run_to_completion(client, headers, url: str, request: str) -> str:
    resp = await client.post(
        "/v1/runs", json={"request": request, "repository_url": url}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]
    decided = await client.post(
        f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers
    )
    assert decided.status_code == 200, decided.text
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed"
    return run_id


async def test_completed_run_leaves_a_decision_and_an_outcome(client):
    headers = _headers()
    url = _repo_url()
    repo_id = await _create_repo(client, headers, url)

    run_id = await _run_to_completion(client, headers, url, "Add a /status endpoint")

    by_kind = {item["kind"]: item for item in await _knowledge(client, headers, repo_id)}
    assert set(by_kind) == {"decision", "outcome"}
    assert by_kind["decision"]["source_run_id"] == run_id
    assert by_kind["outcome"]["source_run_id"] == run_id
    assert "Add a /status endpoint" in by_kind["outcome"]["title"]
    assert by_kind["decision"]["created_by"] is None  # auto-captured, not hand-written


async def test_capture_is_idempotent(client):
    from engine.knowledge.capture import capture_run_memory

    headers = _headers()
    url = _repo_url()
    repo_id = await _create_repo(client, headers, url)
    run_id = await _run_to_completion(client, headers, url, "Add a /status endpoint")

    await capture_run_memory(uuid.UUID(run_id))  # a second capture of the same run
    items = await _knowledge(client, headers, repo_id)
    assert len(items) == 2  # still one decision + one outcome


async def test_rejected_plan_is_remembered_as_a_preference(client):
    headers = _headers()
    url = _repo_url()
    repo_id = await _create_repo(client, headers, url)

    resp = await client.post(
        "/v1/runs",
        json={"request": "Rewrite everything in Rust", "repository_url": url},
        headers=headers,
    )
    run_id = resp.json()["id"]
    decided = await client.post(
        f"/v1/runs/{run_id}/decision", json={"approved": False}, headers=headers
    )
    assert decided.status_code == 200, decided.text

    items = await _knowledge(client, headers, repo_id)
    assert len(items) == 1
    preference = items[0]
    assert preference["kind"] == "preference"
    assert preference["source_run_id"] == run_id
    assert "Rewrite everything in Rust" in preference["content"]


# ── Recall feeding agent context (phase exit criterion) ─────────────────────


async def test_planning_recalls_stored_memory_onto_the_timeline(client):
    headers = _headers()
    url = _repo_url()
    repo_id = await _create_repo(client, headers, url)
    await _add_note(
        client,
        headers,
        repo_id,
        kind="preference",
        title="Endpoints need tests",
        content="Every new endpoint ships with an integration test.",
    )

    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint with tests", "repository_url": url},
        headers=headers,
    )
    run_id = resp.json()["id"]

    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    recalled = [e for e in events if e["type"] == "memory.recalled"]
    assert recalled, "planning did not recall the stored memory"
    titles = [m["title"] for m in recalled[0]["payload"]["memories"]]
    assert "Endpoints need tests" in titles


async def test_planning_without_memory_emits_no_recall_event(client):
    headers = _headers()
    url = _repo_url()
    await _create_repo(client, headers, url)

    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": url},
        headers=headers,
    )
    events = (await client.get(f"/v1/runs/{resp.json()['id']}/events", headers=headers)).json()
    assert not [e for e in events if e["type"] == "memory.recalled"]


def test_format_memories_reads_as_context_not_command():
    assert format_memories([]) == ""
    block = format_memories(
        [
            RecalledMemory(
                id=uuid.uuid4(),
                kind="preference",
                title="Endpoints need tests",
                content="Every new endpoint ships with an integration test.",
                source_run_id=None,
                created_at=None,  # type: ignore[arg-type]
                score=0.9,
            )
        ]
    )
    assert "Team memory" in block
    assert "context, not command" in block
    assert "[preference] Endpoints need tests" in block
