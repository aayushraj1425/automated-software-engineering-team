"""Technical Writer: generate one human-facing document from the index.

One planner-tier model call turns the repository's file map plus the code most
relevant to the chosen kind into a Markdown document — a README, an API
reference, a changelog, or an architecture overview. Context gathering mirrors
the Scrum Master's grounding (distinct file paths from `code_chunks`, plus
hybrid-retrieved chunks for a kind-specific seed query). With LLM_FAKE=1 a
deterministic document listing the real file paths is returned so the whole
path runs offline. Design note: docs/architecture/DOCUMENTATION_SUITE.md.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole, DocumentKind
from engine.db.models import CodeChunk, GeneratedDocument
from engine.indexing.retrieval import retrieve_chunks
from engine.llm.router import model_router

# A document is a summary for people, not an archive — cap what one row holds.
MAX_CONTENT = 24_000
# How much repository to hand the writer as context.
_CONTEXT_FILE_LIMIT = 80
_CODE_CHUNK_LIMIT = 8
_CHUNK_CHARS = 800

# A readable title per kind; the model writes the body under it.
TITLES: dict[str, str] = {
    DocumentKind.README: "README",
    DocumentKind.API_REFERENCE: "API Reference",
    DocumentKind.CHANGELOG: "Changelog",
    DocumentKind.ARCHITECTURE: "Architecture Overview",
}

# What to retrieve so the writer quotes real code for each document kind.
SEED_QUERIES: dict[str, str] = {
    DocumentKind.README: "project overview entry point main setup install configuration usage",
    DocumentKind.API_REFERENCE: "api endpoint route handler request response function public",
    DocumentKind.CHANGELOG: "feature module functionality behavior capability",
    DocumentKind.ARCHITECTURE: "module package component dependency import structure layer",
}

# What each kind asks the writer to produce, appended to the shared prompt.
INSTRUCTIONS: dict[str, str] = {
    DocumentKind.README: (
        "Write a README for this repository: a one-line summary, what it is and "
        "what problem it solves, how to set it up, and how to use it."
    ),
    DocumentKind.API_REFERENCE: (
        "Write an API reference for this repository: the endpoints, public "
        "functions, or commands the code exposes, each with what it takes and "
        "returns. Group related entries."
    ),
    # The snapshot fallback, used only when commit history is unavailable —
    # with history, _CHANGELOG_FROM_HISTORY replaces it (git_history.py).
    DocumentKind.CHANGELOG: (
        "Write a changelog-style summary of what this codebase currently does, "
        "grouped by area of the code. Commit history was unavailable, so "
        "describe the current snapshot, say so in one opening line, and do "
        "not invent version numbers or dates."
    ),
    DocumentKind.ARCHITECTURE: (
        "Write an architecture overview for this repository: the main modules, "
        "what each is responsible for, and how they depend on one another."
    ),
}


_CHANGELOG_FROM_HISTORY = (
    "Write a changelog for this repository from its real commit history "
    "below (one `date hash subject (author)` line per commit, newest "
    "first). Group related commits into themes with the real dates; never "
    "invent version numbers or entries the history does not support."
)
# Cap what the prompt carries — 100 log lines fit comfortably under this.
_HISTORY_CHARS = 12_000


def _kind(kind: DocumentKind | str) -> str:
    return str(DocumentKind(kind))


async def gather_context(
    db: AsyncSession, repository_id: uuid.UUID, kind: DocumentKind | str
) -> tuple[str, str]:
    """The file map and the code most relevant to this document kind, both as
    plain text ready to drop into the writer's prompt."""
    kind = _kind(kind)
    paths = (
        (
            await db.execute(
                select(CodeChunk.path)
                .where(CodeChunk.repository_id == repository_id)
                .distinct()
                .order_by(CodeChunk.path)
                .limit(_CONTEXT_FILE_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    file_map = "\n".join(paths)

    chunks = await retrieve_chunks(db, repository_id, SEED_QUERIES[kind], limit=_CODE_CHUNK_LIMIT)
    excerpts = "\n\n".join(
        f"### {chunk.path} (lines {chunk.start_line}-{chunk.end_line})\n"
        f"```{chunk.language}\n{chunk.content[:_CHUNK_CHARS]}\n```"
        for chunk in chunks
    )
    return file_map, excerpts


async def generate_document(
    kind: DocumentKind | str,
    file_map: str = "",
    code_excerpts: str = "",
    memory: str = "",
    history: str = "",
) -> dict[str, Any]:
    """A `{title, content}` document for the kind. Offline mode returns a fixed
    document that lists the repository's real files. The changelog kind reads
    `history` (real `git log` lines — git_history.py) when the caller could
    fetch it; without it the snapshot fallback applies."""
    kind = _kind(kind)
    title = TITLES[kind]
    if get_settings().llm_fake:
        return {"title": title, "content": _offline_document(kind, file_map, history)}

    spec = get_agent_spec(AgentRole.TECHNICAL_WRITER)
    instruction = INSTRUCTIONS[kind]
    history_block = ""
    if kind == DocumentKind.CHANGELOG and history:
        instruction = _CHANGELOG_FROM_HISTORY
        history_block = f"\n\nCommit history:\n{history[:_HISTORY_CHARS]}"
    map_block = f"\n\nRepository files:\n{file_map}" if file_map else ""
    code_block = f"\n\nRelevant code:\n{code_excerpts}" if code_excerpts else ""
    # Recalled team memory rides along as context, never as command
    # (docs/architecture/KNOWLEDGE_AND_MEMORY.md).
    memory_block = f"\n\n{memory}" if memory else ""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": f"{instruction}{history_block}{map_block}{code_block}{memory_block}",
        },
    ]
    reply = await model_router.complete("planner", messages)
    content = reply.strip()[:MAX_CONTENT] or _offline_document(kind, file_map, history)
    return {"title": title, "content": content}


def _offline_document(kind: str, file_map: str, history: str = "") -> str:
    """A deterministic document so the path runs without a model (LLM_FAKE=1).
    A changelog with history lists the real commit lines, proving the history
    flows end to end in the tests."""
    if kind == DocumentKind.CHANGELOG and history:
        commits = "\n".join(f"- {line}" for line in history.splitlines() if line.strip())
        return (
            f"# {TITLES[kind]}\n\n"
            f"_Generated offline (LLM_FAKE=1) from the repository's commit history._\n\n"
            f"## Commits (newest first)\n\n{commits}"
        )
    files = file_map.strip() or "(the repository has not been indexed yet)"
    return (
        f"# {TITLES[kind]}\n\n"
        f"_Generated offline (LLM_FAKE=1) from the repository index._\n\n"
        f"This is a placeholder {kind.replace('_', ' ')} document. A real model "
        f"produces prose grounded in the files below.\n\n"
        f"## Files in this repository\n\n" + "\n".join(f"- `{path}`" for path in files.splitlines())
    )


async def persist_document(
    db: AsyncSession,
    repository_id: uuid.UUID,
    kind: DocumentKind | str,
    document: dict[str, Any],
    created_by: str | None = None,
) -> GeneratedDocument:
    """Store one generated document. The caller commits."""
    doc = GeneratedDocument(
        repository_id=repository_id,
        kind=_kind(kind),
        title=str(document["title"])[:256],
        content=str(document["content"])[:MAX_CONTENT],
        created_by=created_by,
    )
    db.add(doc)
    return doc
