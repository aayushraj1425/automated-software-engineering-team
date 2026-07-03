import json
import uuid

from tests.conftest import auth_headers


def _last_data_payload(sse_body: str) -> dict:
    lines = [line for line in sse_body.splitlines() if line.startswith("data:")]
    return json.loads(lines[-1].removeprefix("data:").strip())


async def test_chat_streams_and_persists(client):
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    headers = auth_headers(user_id)

    resp = await client.post("/v1/chat", json={"message": "hello there"}, headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: token" in body
    assert "event: done" in body

    done = _last_data_payload(body)
    conversation_id = done["conversation_id"]

    msgs = (
        await client.get(f"/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hello there"
    assert "canned reply" in msgs[1]["content"]

    convs = (await client.get("/v1/conversations", headers=headers)).json()
    assert [c["id"] for c in convs] == [conversation_id]
    assert convs[0]["title"] == "hello there"


async def test_chat_continues_existing_conversation(client):
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    headers = auth_headers(user_id)

    first = await client.post("/v1/chat", json={"message": "first"}, headers=headers)
    conversation_id = _last_data_payload(first.text)["conversation_id"]

    second = await client.post(
        "/v1/chat",
        json={"message": "second", "conversation_id": conversation_id},
        headers=headers,
    )
    assert second.status_code == 200
    assert _last_data_payload(second.text)["conversation_id"] == conversation_id

    msgs = (
        await client.get(f"/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


async def test_conversations_are_owner_scoped(client):
    owner = f"user_{uuid.uuid4().hex[:8]}"
    intruder = f"user_{uuid.uuid4().hex[:8]}"

    resp = await client.post("/v1/chat", json={"message": "private"}, headers=auth_headers(owner))
    conversation_id = _last_data_payload(resp.text)["conversation_id"]

    stolen = await client.get(
        f"/v1/conversations/{conversation_id}/messages", headers=auth_headers(intruder)
    )
    assert stolen.status_code == 404

    hijack = await client.post(
        "/v1/chat",
        json={"message": "inject", "conversation_id": conversation_id},
        headers=auth_headers(intruder),
    )
    assert hijack.status_code == 404


async def test_chat_rejects_empty_message(client):
    resp = await client.post("/v1/chat", json={"message": ""}, headers=auth_headers())
    assert resp.status_code == 422
