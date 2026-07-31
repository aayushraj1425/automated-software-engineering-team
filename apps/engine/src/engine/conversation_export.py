"""Build a markdown transcript of a chat conversation — a shareable record of
a question-and-answer session, the chat parallel to the run report.

A pure function over the conversation and its messages: no model call, no
database, no network, so it works offline and is trivially testable.

Design note: docs/architecture/chat/CONVERSATION_EXPORT.md.
"""

from engine.db.models import Conversation, Message

_ROLE_LABEL = {"user": "You", "assistant": "Assistant"}


def _citation_line(citation: dict) -> str:
    """One `path:start–end` reference, defensive about a missing field."""
    path = str(citation.get("path", "?"))
    start = citation.get("start_line")
    end = citation.get("end_line")
    if start is not None and end is not None:
        return f"{path}:{start}–{end}"
    return path


def build_conversation_transcript(conversation: Conversation, messages: list[Message]) -> str:
    """One markdown document of a conversation: its title, then each turn as
    **You:** / **Assistant:** in order, with any citations listed under the
    answer. Defensive about unset fields so a fresh or odd conversation still
    renders."""
    title = (conversation.title or "").strip() or "Conversation"
    lines: list[str] = [f"# {title}", ""]

    if not messages:
        lines += ["_No messages yet._", ""]
    for message in messages:
        label = _ROLE_LABEL.get(message.role, message.role.capitalize())
        lines.append(f"**{label}:**")
        lines.append("")
        lines.append((message.content or "").strip() or "_(empty)_")
        if message.role == "assistant" and message.citations:
            lines.append("")
            lines.append("Sources:")
            lines += [f"- {_citation_line(citation)}" for citation in message.citations]
        lines.append("")

    lines += ["---", "", "_Exported from ASEP._", ""]
    return "\n".join(lines)
