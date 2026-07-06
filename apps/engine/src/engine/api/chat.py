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
from engine.indexing.retrieval import retrieve_chunks
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
    async with session_scope() as db:
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
        # so an unknown repository rejects the request cleanly.
        grounding: str | None = None
        citations: list[dict] | None = None
        if req.repository_id is not None:
            repo = await db.get(Repository, req.repository_id)
            if repo is None or repo.owner_id != principal.user_id:
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
        if grounding is not None:
            history = [{"role": "system", "content": grounding}, *history]
        await db.commit()

    structlog.contextvars.bind_contextvars(
        conversation_id=str(conversation_id), user_id=principal.user_id
    )

    async def event_stream() -> AsyncIterator[str]:
        parts: list[str] = []
        if citations is not None:
            yield _sse("citations", {"citations": citations})
        try:
            async for chunk in chat_graph.astream({"messages": history}, stream_mode="custom"):
                if isinstance(chunk, dict) and chunk.get("type") == "token":
                    parts.append(chunk["text"])
                    yield _sse("token", {"text": chunk["text"]})
        except Exception:
            log.exception("chat.stream_failed")
            yield _sse("error", {"message": "The model call failed. Check engine logs."})
            return

        async with session_scope() as db:
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
