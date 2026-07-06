"""Grounded chat: answers about a connected repository cite their sources.

Offline the reply text is canned, but retrieval, the citations SSE event, and
citation persistence all run for real against an indexed fixture repository.
"""

import json
import uuid

from engine.evaluation import prepare_fixture_repo
from tests.conftest import auth_headers


def _last_data_payload(sse_body: str) -> dict:
    lines = [line for line in sse_body.splitlines() if line.startswith("data:")]
    return json.loads(lines[-1].removeprefix("data:"))


def _citations_payload(sse_body: str) -> list[dict]:
    events = sse_body.split("\n\n")
    for event in events:
        if event.startswith("event: citations"):
            (data_line,) = [line for line in event.splitlines() if line.startswith("data:")]
            return json.loads(data_line.removeprefix("data:"))["citations"]
    raise AssertionError("no citations event in the stream")


async def _connect_and_index(client, headers, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    repo = (
        await client.post("/v1/repositories", json={"url": str(origin)}, headers=headers)
    ).json()
    # httpx's ASGI transport waits for background tasks — indexing is done here
    await client.post(f"/v1/repositories/{repo['id']}/index", headers=headers)
    return repo


async def test_grounded_chat_streams_and_persists_citations(client, tmp_path):
    headers = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    repo = await _connect_and_index(client, headers, tmp_path)

    resp = await client.post(
        "/v1/chat",
        json={"message": "Where does the API list its items?", "repository_id": repo["id"]},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: token" in body
    assert "event: done" in body

    citations = _citations_payload(body)
    assert citations, "grounded chat must name its sources"
    assert {"path", "start_line", "end_line", "score"} <= set(citations[0])

    conversation_id = _last_data_payload(body)["conversation_id"]
    msgs = (
        await client.get(f"/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()
    assistant = msgs[-1]
    assert assistant["role"] == "assistant"
    assert assistant["citations"] == citations  # sources survive a reload


async def test_chat_without_repository_has_no_citations(client):
    headers = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    resp = await client.post("/v1/chat", json={"message": "hello"}, headers=headers)
    assert resp.status_code == 200
    assert "event: citations" not in resp.text

    conversation_id = _last_data_payload(resp.text)["conversation_id"]
    msgs = (
        await client.get(f"/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()
    assert msgs[-1]["citations"] is None


async def test_grounded_chat_is_owner_scoped(client, tmp_path):
    owner = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    intruder = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    repo = await _connect_and_index(client, owner, tmp_path)

    resp = await client.post(
        "/v1/chat",
        json={"message": "what is here?", "repository_id": repo["id"]},
        headers=intruder,
    )
    assert resp.status_code == 404
