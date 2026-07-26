"""Conversation management: rename and delete, owner-scoped.

Conversations are personal (never shared with an organization), so the only
access rule is owner-or-404. Seeded directly rather than via the chat SSE
stream, so the assertions stay deterministic.
"""

import uuid

from engine.db.models import Conversation, Message
from engine.db.session import session_scope
from tests.conftest import auth_headers


async def _seed_conversation(user: str, title: str | None = "Old title") -> uuid.UUID:
    async with session_scope(user_id=user) as session:
        conversation = Conversation(user_id=user, title=title)
        session.add(conversation)
        await session.commit()
        return conversation.id


async def test_rename_then_delete_a_conversation(client, prepared_db):
    user = f"conv_{uuid.uuid4().hex[:8]}"
    conversation_id = await _seed_conversation(user)
    headers = auth_headers(user)

    renamed = await client.patch(
        f"/v1/conversations/{conversation_id}", json={"title": "  New title  "}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "New title"  # trimmed

    blank = await client.patch(
        f"/v1/conversations/{conversation_id}", json={"title": "   "}, headers=headers
    )
    assert blank.status_code == 422  # a blank title is rejected

    deleted = await client.delete(f"/v1/conversations/{conversation_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/v1/conversations", headers=headers)).json() == []


async def test_conversation_ops_are_owner_scoped(client, prepared_db):
    owner = f"conv_{uuid.uuid4().hex[:8]}"
    conversation_id = await _seed_conversation(owner, title="mine")
    intruder = auth_headers(f"conv_{uuid.uuid4().hex[:8]}")

    rename = await client.patch(
        f"/v1/conversations/{conversation_id}", json={"title": "hijack"}, headers=intruder
    )
    assert rename.status_code == 404
    delete = await client.delete(f"/v1/conversations/{conversation_id}", headers=intruder)
    assert delete.status_code == 404

    # The owner's conversation is untouched.
    owned = (await client.get("/v1/conversations", headers=auth_headers(owner))).json()
    assert [c["title"] for c in owned] == ["mine"]


async def test_export_conversation_returns_a_markdown_transcript(client, prepared_db):
    user = f"conv_{uuid.uuid4().hex[:8]}"
    async with session_scope(user_id=user) as session:
        conversation = Conversation(user_id=user, title="Export me")
        session.add(conversation)
        await session.flush()
        session.add_all(
            [
                Message(conversation_id=conversation.id, role="user", content="Hi there"),
                Message(conversation_id=conversation.id, role="assistant", content="Hello!"),
            ]
        )
        await session.commit()
        conversation_id = conversation.id

    resp = await client.get(
        f"/v1/conversations/{conversation_id}/export", headers=auth_headers(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"].endswith(".md")
    assert body["markdown"].startswith("# Export me")
    assert "**You:**" in body["markdown"] and "Hi there" in body["markdown"]
    assert "Hello!" in body["markdown"]


async def test_export_conversation_is_owner_scoped(client, prepared_db):
    owner = f"conv_{uuid.uuid4().hex[:8]}"
    conversation_id = await _seed_conversation(owner, title="mine")
    intruder = auth_headers(f"conv_{uuid.uuid4().hex[:8]}")

    resp = await client.get(f"/v1/conversations/{conversation_id}/export", headers=intruder)
    assert resp.status_code == 404


async def _seed_with_message(user: str, title: str, message: str) -> uuid.UUID:
    async with session_scope(user_id=user) as session:
        conversation = Conversation(user_id=user, title=title)
        session.add(conversation)
        await session.flush()
        session.add(Message(conversation_id=conversation.id, role="user", content=message))
        await session.commit()
        return conversation.id


async def test_search_matches_title_or_message_text(client, prepared_db):
    user = f"conv_{uuid.uuid4().hex[:8]}"
    await _seed_with_message(user, title="Retrieval bug", message="unrelated chatter")
    await _seed_with_message(user, title="Weekend plans", message="the deployment pipeline broke")
    headers = auth_headers(user)

    async def titles(q: str | None) -> list[str]:
        params = {"q": q} if q is not None else {}
        resp = await client.get("/v1/conversations", params=params, headers=headers)
        assert resp.status_code == 200
        return sorted(c["title"] for c in resp.json())

    assert await titles(None) == ["Retrieval bug", "Weekend plans"]  # no query, full list
    assert await titles("retrieval") == ["Retrieval bug"]  # by title, case-insensitive
    assert await titles("deployment") == ["Weekend plans"]  # by message content
    assert await titles("   ") == ["Retrieval bug", "Weekend plans"]  # blank is a no-op
    assert await titles("nothing here") == []


async def test_search_treats_wildcards_literally_and_stays_owner_scoped(client, prepared_db):
    owner = f"conv_{uuid.uuid4().hex[:8]}"
    await _seed_with_message(owner, title="50% off sale", message="hi")
    await _seed_with_message(owner, title="quarterly review", message="hi")

    owner_headers = auth_headers(owner)
    literal = await client.get("/v1/conversations", params={"q": "50%"}, headers=owner_headers)
    # A literal % is escaped, so it matches the "50% off" title, not everything.
    assert [c["title"] for c in literal.json()] == ["50% off sale"]

    # Another user's search sees none of the owner's conversations.
    intruder = auth_headers(f"conv_{uuid.uuid4().hex[:8]}")
    theirs = await client.get("/v1/conversations", params={"q": "50%"}, headers=intruder)
    assert theirs.json() == []
