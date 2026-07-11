import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from engine.config import EMBEDDING_DIM
from engine.db.enums import Priority, RunStatus, TaskStatus, WorkItemKind, WorkItemStatus


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Identity tables (user/session/account/organization/member) are owned by
# better-auth and created by its CLI migration — engine tables reference
# better-auth ids as plain text with no FKs (ADR-0007).


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="github")
    url: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    status: Mapped[str] = mapped_column(String(32), default="connected")
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sources behind a grounded answer: [{path, start_line, end_line, score}]
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ── Agent runtime (docs/architecture/AGENT_RUNTIME.md) ──────────────────────


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    org_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED, index=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal(0), server_default="0"
    )
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tasks: Mapped[list["AgentTask"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentTask.sequence",
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Artifact.created_at"
    )


class AgentTask(Base, TimestampMixin):
    __tablename__ = "agent_tasks"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_tasks_run_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING, index=True)
    depends_on: Mapped[list[str]] = mapped_column(JSONB, default=list)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="tasks")


class AgentEvent(Base):
    """Append-only run timeline. The bigint identity pk gives the SSE stream a
    total order and a resume cursor (Last-Event-ID) — see AGENT_RUNTIME.md."""

    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True
    )
    agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(256))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CodeChunk(Base):
    """One indexed piece of a repository file (Repository Intelligence).
    Re-indexing replaces all of a repository's chunks."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        # GIN index over the generated tsvector powers the full-text arm of
        # hybrid retrieval (design note: docs/architecture/HYBRID_RETRIEVAL.md).
        Index("ix_code_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        # HNSW approximate-nearest-neighbor index keeps cosine-distance vector
        # search fast as repositories grow (docs/architecture/INCREMENTAL_INDEXING.md).
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(32))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # Kept in sync by Postgres; the full-text search arm matches against it.
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CodeEdge(Base):
    """One first-party import: `source_path` imports `target_path` within the
    same repository (Repository Intelligence). Re-indexing replaces a
    repository's edges. Design note: docs/architecture/DEPENDENCY_GRAPH.md."""

    __tablename__ = "code_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    source_path: Mapped[str] = mapped_column(String(512))
    target_path: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(32), default="import")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IndexedFile(Base):
    """One source file's content fingerprint from the last index, letting a
    re-index re-embed only the files whose bytes changed (Repository
    Intelligence). Design note: docs/architecture/INCREMENTAL_INDEXING.md."""

    __tablename__ = "indexed_files"
    __table_args__ = (UniqueConstraint("repository_id", "path", name="uq_indexed_files_repo_path"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of the file bytes
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ── Planning Suite (docs/architecture/PLANNING_SUITE.md) ────────────────────


class WorkItem(Base, TimestampMixin):
    """A durable, repository-scoped unit of planned work — a backlog item.

    Distinct from AgentTask: an AgentTask is ephemeral and lives inside one run,
    while a WorkItem is planned once and lives on (estimated, reordered, blocked)
    until a coding run implements it and records itself in `implemented_by_run_id`.
    """

    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default=WorkItemKind.FEATURE)
    status: Mapped[str] = mapped_column(String(32), default=WorkItemStatus.PROPOSED, index=True)
    # Relative size (small / medium / large); null until the agent estimates it.
    estimate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default=Priority.MEDIUM, index=True)
    milestone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Ids of other work items this one waits on (mirrors AgentTask.depends_on).
    depends_on: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # The agent's one-sentence reasoning behind the estimate / priority.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Manual ordering within a milestone on the task board.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    implemented_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
