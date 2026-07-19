import json
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from engine.agents.chat_graph import chat_graph
from engine.auth import Principal, require_service_auth
from engine.db.models import AuditLog, Conversation, Message, Repository
from engine.db.session import session_scope
from engine.db.visibility import can_access
from engine.indexing.retrieval import retrieve_chunks
from engine.knowledge.recall import format_memories, recall_memories
from engine.llm.keys import load_provider_keys, provider_keys_var
from engine.llm.router import model_router

router = APIRouter()
log = structlog.get_logger(__name__)

HISTORY_LIMIT = 50
EXCERPT_CHARS = 1_500

GROUNDING_PROMPT = (
    "The user connected a repository; the code excerpts below were retrieved "
    "for their question. Ground your answer in them and cite files as "
    "path:start_line-end_line. If the excerpts do not contain the answer, say "
    "what is missing instead of guessing.\n\n{excerpts}"
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    conversation_id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/v1/chat")
async def chat(
    req: ChatRequest,
    principal: Principal = Depends(require_service_auth),
) -> StreamingResponse:
    # Persist the user message and load history before streaming starts —
    # streaming generators must not rely on request-scoped sessions.
    async with session_scope(user_id=principal.user_id, org_id=principal.org_id) as db:
        # Conversations stay personal even under an active organization
        # (ORGANIZATION_SHARING.md) — owner check, not visibility.
        if req.conversation_id is not None:
            conversation = await db.get(Conversation, req.conversation_id)
            if conversation is None or conversation.user_id != principal.user_id:
                raise HTTPException(status_code=404, detail="Conversation not found")
        else:
            conversation = Conversation(
                user_id=principal.user_id,
                org_id=principal.org_id,
                title=req.message[:80],
            )
            db.add(conversation)
            await db.flush()

        # Grounding: retrieve the closest code chunks before anything persists,
        # so an unknown repository rejects the request cleanly. Team memory
        # rides along the same way (KNOWLEDGE_AND_MEMORY.md): the memories most
        # relevant to the question join the system context next to the code.
        grounding: str | None = None
        citations: list[dict] | None = None
        memory_block: str | None = None
        recalled: list[dict] | None = None
        if req.repository_id is not None:
            repo = await db.get(Repository, req.repository_id)
            if repo is None or not can_access(principal, repo.owner_id, repo.org_id):
                raise HTTPException(status_code=404, detail="Repository not found")
            chunks = await retrieve_chunks(db, repo.id, req.message)
            if chunks:
                citations = [
                    {
                        "path": c.path,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "score": c.score,
                    }
                    for c in chunks
                ]
                excerpts = "\n\n".join(
                    f"--- {c.path}:{c.start_line}-{c.end_line}\n{c.content[:EXCERPT_CHARS]}"
                    for c in chunks
                )
                grounding = GROUNDING_PROMPT.format(excerpts=excerpts)
            memories = await recall_memories(db, repo.id, req.message)
            if memories:
                memory_block = format_memories(memories)
                recalled = [{"kind": m.kind, "title": m.title, "score": m.score} for m in memories]

        conversation_id = conversation.id
        db.add(Message(conversation_id=conversation_id, role="user", content=req.message))
        db.add(
            AuditLog(
                actor_id=principal.user_id,
                action="chat.message",
                target=str(conversation_id),
                meta={"length": len(req.message)},
            )
        )

        history_rows = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(HISTORY_LIMIT)
            )
        ).scalars()
        history = [{"role": m.role, "content": m.content} for m in reversed(list(history_rows))]
        preamble = "\n\n".join(part for part in (grounding, memory_block) if part)
        if preamble:
            history = [{"role": "system", "content": preamble}, *history]
        # The caller's own provider keys, for the streamed model call below
        # (PROVIDER_KEYS.md); no keys means the .env keys apply.
        user_keys = await load_provider_keys(db, principal.user_id, principal.org_id)
        await db.commit()

    structlog.contextvars.bind_contextvars(
        conversation_id=str(conversation_id), user_id=principal.user_id
    )

    async def event_stream() -> AsyncIterator[str]:
        provider_keys_var.set(user_keys)  # inside the task that runs the stream
        parts: list[str] = []
        if citations is not None:
            yield _sse("citations", {"citations": citations})
        if recalled is not None:
            # Like citations, the recall is visible to the client — the UI can
            # show which memories informed the answer.
            yield _sse("memory", {"memories": recalled})
        try:
            async for chunk in chat_graph.astream({"messages": history}, stream_mode="custom"):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    parts.append(chunk["text"])
                    yield _sse("token", {"text": chunk["text"]})
        except Exception:
            log.exception("chat.stream_failed")
            yield _sse("error", {"message": "The model call failed. Check engine logs."})
            return

        async with session_scope(user_id=principal.user_id, org_id=principal.org_id) as db:
            assistant = Message(
                conversation_id=conversation_id,
                role="assistant",
                content="".join(parts),
                model=model_router.resolve("coder"),
                citations=citations,
            )
            db.add(assistant)
            await db.commit()
            message_id = assistant.id

        yield _sse("done", {"conversation_id": str(conversation_id), "message_id": str(message_id)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
