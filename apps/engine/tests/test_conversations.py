"""Conversation management: rename and delete, owner-scoped.

Conversations are personal (never shared with an organization), so the only
access rule is owner-or-404. Seeded directly rather than via the chat SSE
stream, so the assertions stay deterministic.
"""

import uuid

from engine.db.models import Conversation
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
