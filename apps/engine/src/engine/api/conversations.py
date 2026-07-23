import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
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


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=256)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title cannot be blank")
        return stripped


async def _owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, principal: Principal
) -> Conversation:
    """The caller's conversation, or 404 — a conversation is personal, never
    shared with an organization (ORGANIZATION_SHARING.md)."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


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


@router.patch("/v1/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID,
    body: ConversationRename,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> ConversationOut:
    conversation = await _owned_conversation(db, conversation_id, principal)
    conversation.title = body.title
    await db.commit()
    await db.refresh(conversation)
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.delete("/v1/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a conversation and its messages (cascade), owner-scoped."""
    conversation = await _owned_conversation(db, conversation_id, principal)
    await db.delete(conversation)
    await db.commit()


@router.get("/v1/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    await _owned_conversation(db, conversation_id, principal)
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
