"""The conversation transcript: a shareable markdown export built from the rows.

Pure function, no DB — the objects are constructed in memory. Design note:
docs/architecture/chat/CONVERSATION_EXPORT.md.
"""

import uuid

from engine.conversation_export import build_conversation_transcript
from engine.db.models import Conversation, Message


def _msg(role: str, content: str, citations=None) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role=role,
        content=content,
        citations=citations,
    )


def test_transcript_renders_turns_and_citations():
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title="Where are items listed?")
    messages = [
        _msg("user", "Where are items listed?"),
        _msg(
            "assistant",
            "In the catalog module.",
            citations=[{"path": "app/catalog.py", "start_line": 10, "end_line": 20, "score": 0.9}],
        ),
    ]

    md = build_conversation_transcript(conversation, messages)

    assert md.startswith("# Where are items listed?")
    assert "**You:**" in md
    assert "**Assistant:**" in md
    assert "In the catalog module." in md
    assert "Sources:" in md
    assert "- app/catalog.py:10–20" in md
    assert md.rstrip().endswith("_Exported from ASEP._")


def test_transcript_is_defensive_about_empty_and_untitled():
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title=None)

    md = build_conversation_transcript(conversation, [])
    assert md.startswith("# Conversation")  # untitled falls back
    assert "_No messages yet._" in md

    # An assistant turn with no citations shows no Sources block.
    one = build_conversation_transcript(conversation, [_msg("assistant", "Hi", citations=None)])
    assert "Sources:" not in one
