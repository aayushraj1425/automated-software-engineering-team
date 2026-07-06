import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.models import Conversation, Message
from engine.db.session import get_session

router = APIRouter()


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    model: str | None
    citations: list[dict] | None
    created_at: datetime


@router.get("/v1/conversations")
async def list_conversations(
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[ConversationOut]:
    rows = (
        (
            await db.execute(
                select(Conversation)
                .where(Conversation.user_id == principal.user_id)
                .order_by(Conversation.updated_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at)
        for c in rows
    ]


@router.get("/v1/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            model=m.model,
            citations=m.citations,
            created_at=m.created_at,
        )
        for m in rows
    ]
