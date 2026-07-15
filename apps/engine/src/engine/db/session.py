from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from engine.auth import peek_user_id
from engine.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_RLS_USER_KEY = "rls_user_id"


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def bind_session_to_user(session: AsyncSession, user_id: str) -> None:
    """Pin the session to one user: every transaction it opens carries the
    transaction-local ``app.user_id`` setting, and the row-level-security
    policies (db/rls.py) restrict it to that user's rows — even when a query
    forgets its WHERE clause. Unpinned sessions are the trusted internal
    context (runner, webhooks, migrations) and behave as before RLS."""
    session.info[_RLS_USER_KEY] = user_id


@event.listens_for(Session, "after_begin")
def _apply_rls_context(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Re-applied at the start of *every* transaction, so a mid-request
    commit cannot drop the pin; transaction-local (`set_config(..., true)`),
    so nothing leaks back into the connection pool."""
    user_id: Any = session.info.get(_RLS_USER_KEY)
    if user_id:
        connection.exec_driver_sql("SELECT set_config('app.user_id', %s, true)", (user_id,))


@asynccontextmanager
async def session_scope(user_id: str | None = None) -> AsyncIterator[AsyncSession]:
    """Explicit session context. Prefer this over the request-scoped dependency
    inside streaming generators — FastAPI tears down yield-dependencies before
    a StreamingResponse body finishes. Pass ``user_id`` to pin the session to
    that user's rows; without it the session runs in the trusted internal
    context (see bind_session_to_user)."""
    async with get_sessionmaker()() as session:
        if user_id is not None:
            bind_session_to_user(session, user_id)
        yield session


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for plain (non-streaming) endpoints. Pins the
    session to the verified bearer token's subject — the same token
    require_service_auth checks — so every route's queries are confined to
    the caller's rows at the database level."""
    async with get_sessionmaker()() as session:
        user_id = peek_user_id(request)
        if user_id is not None:
            bind_session_to_user(session, user_id)
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
