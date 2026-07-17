"""Documentation API: generate and keep human-facing docs (Documentation Suite).

Owner-scoped like the knowledge and work-items APIs. Generating a document runs
the Technical Writer over the repository index and stores the Markdown; the page
then lists, reads, and deletes documents. Design note:
docs/architecture/DOCUMENTATION_SUITE.md.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.auth import Principal, require_service_auth
from engine.db.enums import DocumentKind
from engine.db.models import GeneratedDocument, Repository
from engine.db.session import get_session
from engine.db.visibility import can_access
from engine.docs.generator import MAX_CONTENT, gather_context, generate_document, persist_document
from engine.docs.git_history import collect_history
from engine.knowledge.recall import format_memories, recall_memories
from engine.llm.keys import load_provider_keys, provider_keys_var

router = APIRouter()

_LIST_LIMIT = 100
# Enough words for recall to find memory relevant to the document kind.
_RECALL_QUERIES: dict[str, str] = {
    DocumentKind.README: "project overview setup usage conventions",
    DocumentKind.API_REFERENCE: "api endpoints interface conventions",
    DocumentKind.CHANGELOG: "features behavior what changed",
    DocumentKind.ARCHITECTURE: "architecture modules design decisions",
}


class DocumentIn(BaseModel):
    kind: DocumentKind = DocumentKind.README


class DocumentUpdate(BaseModel):
    """An in-place correction: the person who knows the project fixes the
    prose. Content is required; the title only changes when sent."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT)
    title: str | None = Field(default=None, min_length=1, max_length=256)


class DocumentOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    kind: str
    title: str
    content: str
    created_by: str | None
    created_at: datetime
    updated_at: datetime


def _document_out(doc: GeneratedDocument) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        repository_id=doc.repository_id,
        kind=doc.kind,
        title=doc.title,
        content=doc.content,
        created_by=doc.created_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


async def _visible_repository(
    db: AsyncSession, repository_id: uuid.UUID, principal: Principal
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None or not can_access(principal, repo.owner_id, repo.org_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.get("/v1/repositories/{repository_id}/documents")
async def list_documents(
    repository_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    """The repository's generated documents, newest first."""
    await _visible_repository(db, repository_id, principal)
    rows = (
        (
            await db.execute(
                select(GeneratedDocument)
                .where(GeneratedDocument.repository_id == repository_id)
                .order_by(GeneratedDocument.created_at.desc())
                .limit(_LIST_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [_document_out(doc) for doc in rows]


@router.post("/v1/repositories/{repository_id}/documents", status_code=201)
async def generate_repository_document(
    repository_id: uuid.UUID,
    body: DocumentIn,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Technical Writer: generate a document from the index and save it.
    The changelog additionally reads the repository's real commit history
    (bounded shallow fetch — engine/docs/git_history.py); when the fetch
    fails it falls back to the snapshot summary honestly."""
    repo = await _visible_repository(db, repository_id, principal)
    file_map, code_excerpts = await gather_context(db, repository_id, body.kind)
    history = ""
    if body.kind == DocumentKind.CHANGELOG:
        history = await collect_history(repo.url)
    memory = format_memories(
        await recall_memories(db, repository_id, _RECALL_QUERIES[str(body.kind)])
    )
    # The caller's own provider keys for the writer call (PROVIDER_KEYS.md).
    provider_keys_var.set(await load_provider_keys(db, principal.user_id))
    document = await generate_document(body.kind, file_map, code_excerpts, memory, history)
    doc = await persist_document(
        db, repository_id, body.kind, document, created_by=principal.user_id
    )
    await db.commit()
    await db.refresh(doc)
    return _document_out(doc)


@router.put("/v1/repositories/{repository_id}/documents/{document_id}")
async def update_document(
    repository_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentUpdate,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Replace a document's content (and optionally its title) in place —
    an edit is never silently overwritten: regenerating creates a new row."""
    await _visible_repository(db, repository_id, principal)
    doc = await db.get(GeneratedDocument, document_id)
    if doc is None or doc.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.content = body.content
    if body.title is not None:
        doc.title = body.title.strip()[:256]
    await db.commit()
    await db.refresh(doc)
    return _document_out(doc)


@router.delete("/v1/repositories/{repository_id}/documents/{document_id}", status_code=204)
async def delete_document(
    repository_id: uuid.UUID,
    document_id: uuid.UUID,
    principal: Principal = Depends(require_service_auth),
    db: AsyncSession = Depends(get_session),
) -> None:
    await _visible_repository(db, repository_id, principal)
    doc = await db.get(GeneratedDocument, document_id)
    if doc is None or doc.repository_id != repository_id:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
