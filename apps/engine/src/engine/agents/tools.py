"""The agents' toolbox: read, write, search, git, and the task board.

Each tool is an async function plus a JSON schema (the part the AI model
sees). call_tool() is the single dispatcher: it checks the tool is on the
agent's allow-list (deny by default, per the registry), runs it, and turns
any ToolError into a plain error message the agent can read and react to.
Every path an agent supplies goes through the jail before anything is touched.
The task-board tools write agent_tasks directly (durable, and the UI board
sees the change immediately); the supervisor learns about the changes when
the current task's executor returns (TASK_BOARD_TOOLS.md).
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from engine.db.enums import AgentRole, TaskStatus
from engine.db.models import AgentEvent, AgentRun, AgentTask
from engine.db.session import session_scope
from engine.indexing.retrieval import retrieve_chunks
from engine.workspace.jail import JailViolation, resolve_inside
from engine.workspace.manager import Workspace, WorkspaceError, run_git

MAX_READ_BYTES = 64_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 50
MAX_SEARCH_FILE_BYTES = 512_000
SEARCH_CODE_RESULTS = 6
SEARCH_CODE_SNIPPET_CHARS = 500

# A looping agent must not flood the run with work (TASK_BOARD_TOOLS.md).
MAX_BOARD_TASKS = 30
# New tasks take engineer roles only — never the reviewer or the planners.
_TASK_ROLES = (AgentRole.BACKEND, AgentRole.FRONTEND, AgentRole.DEVOPS)
_UNFINISHED = (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)


class ToolError(Exception):
    """A tool refused or failed; the message goes back to the agent."""


async def list_dir(ws: Workspace, path: str = ".") -> str:
    target = _safe(ws, path)
    if not target.is_dir():
        raise ToolError(f"not a folder: {path}")
    lines = []
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    for entry in entries[:MAX_LIST_ENTRIES]:
        if entry.name == ".git":
            continue
        kind = "file" if entry.is_file() else "dir "
        size = f" ({entry.stat().st_size} bytes)" if entry.is_file() else ""
        lines.append(f"{kind} {entry.name}{size}")
    if len(entries) > MAX_LIST_ENTRIES:
        lines.append(f"... and {len(entries) - MAX_LIST_ENTRIES} more entries")
    return "\n".join(lines) or "(empty folder)"


async def read_file(ws: Workspace, path: str) -> str:
    target = _safe(ws, path)
    if not target.is_file():
        raise ToolError(f"file not found: {path}")
    if target.stat().st_size > MAX_READ_BYTES:
        raise ToolError(f"file too large to read whole ({target.stat().st_size} bytes): {path}")
    return target.read_text(encoding="utf-8", errors="replace")


async def write_file(ws: Workspace, path: str, content: str) -> str:
    target = _safe(ws, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return f"wrote {len(content.encode('utf-8'))} bytes to {path}"


def _patch_paths(patch: str) -> tuple[list[str], bool]:
    """Every file path a unified diff touches, plus whether it uses the
    git-style ``a/``/``b/`` prefixes (``-p1``) or bare paths (``-p0``)."""
    paths: list[str] = []
    prefixed = 0
    bare = 0
    for line in patch.splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        target = line[4:].split("\t")[0].strip()
        if not target or target == "/dev/null":
            continue
        if target.startswith(("a/", "b/")):
            prefixed += 1
            target = target[2:]
        else:
            bare += 1
        if target and target not in paths:
            paths.append(target)
    return paths, prefixed >= bare


async def apply_patch(ws: Workspace, patch: str) -> str:
    """Apply a unified diff to the workspace — the edit is the size of the
    change, not the file (APPLY_PATCH_TOOL.md). Every path in the diff goes
    through the jail before git ever sees the patch; `git apply --check`
    dry-runs it first, so a patch applies completely or not at all."""
    if not patch.strip() or "+++" not in patch or "@@" not in patch:
        raise ToolError("not a unified diff — it needs ---/+++ headers and @@ hunks")
    if not patch.endswith("\n"):
        patch += "\n"
    paths, prefixed = _patch_paths(patch)
    if not paths:
        raise ToolError("the patch names no files")
    for path in paths:
        _safe(ws, path)  # jail first, git second (ADR-0008 defense in depth)

    strip = "-p1" if prefixed else "-p0"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".patch", delete=False, encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(patch)
        patch_file = handle.name
    try:
        try:
            await run_git(
                ws.path, "apply", "--check", strip, "--ignore-whitespace", "--", patch_file
            )
            await run_git(ws.path, "apply", strip, "--ignore-whitespace", "--", patch_file)
        except WorkspaceError as exc:
            raise ToolError(
                f"the patch does not apply: {exc} — re-read the file and "
                "regenerate the diff against its current content"
            ) from exc
    finally:
        Path(patch_file).unlink(missing_ok=True)
    names = ", ".join(paths[:5]) + ("…" if len(paths) > 5 else "")
    return f"patched {len(paths)} file(s): {names}"


async def search(ws: Workspace, text: str, path: str = ".") -> str:
    """Case-insensitive plain-text search across the workspace files."""
    if not text.strip():
        raise ToolError("search text is empty")
    root = _safe(ws, path)
    needle = text.lower()

    def _scan() -> str:
        # Walks and reads the whole tree — run in a thread so a large
        # repository cannot stall the event loop (and every other run).
        hits: list[str] = []
        for file in sorted(root.rglob("*")):
            if ".git" in file.parts or not file.is_file():
                continue
            if file.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            rel = file.relative_to(ws.path)
            for lineno, line in enumerate(
                file.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if needle in line.lower():
                    hits.append(f"{rel.as_posix()}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_RESULTS:
                        return "\n".join(hits) + "\n... (more results cut off)"
        return "\n".join(hits) or f"no matches for {text!r}"

    return await asyncio.to_thread(_scan)


async def search_code(ws: Workspace, query: str) -> str:
    """Meaning-based search over the run repository's code index.

    The repository is found through the workspace's run id, so an agent can
    only ever search the index of the repository its run works on. A missing
    index is guidance, not an error — the agent falls back to plain search.
    """
    if not query.strip():
        raise ToolError("search query is empty")
    async with session_scope() as db:
        run = await db.get(AgentRun, ws.run_id)
        if run is None:
            return "no code index is connected to this run; use the plain 'search' tool instead"
        chunks = await retrieve_chunks(db, run.repository_id, query, limit=SEARCH_CODE_RESULTS)
    if not chunks:
        return "the repository has no code index yet; use the plain 'search' tool instead"
    return "\n\n".join(
        f"{c.path}:{c.start_line}-{c.end_line} (score {c.score:.2f})\n"
        f"{c.content[:SEARCH_CODE_SNIPPET_CHARS]}"
        for c in chunks
    )


async def add_task(ws: Workspace, title: str, description: str = "", role: str = "backend") -> str:
    """Append a newly discovered task to this run's board. It lands pending
    with the next sequence and no dependencies; the supervisor schedules it
    after the current task finishes (TASK_BOARD_TOOLS.md)."""
    title = title.strip()
    if not title:
        raise ToolError("task title is empty")
    if role not in _TASK_ROLES:
        allowed = ", ".join(_TASK_ROLES)
        raise ToolError(f"role {role!r} cannot take tasks — choose one of: {allowed}")
    async with session_scope() as db:
        count = (
            await db.execute(
                select(func.count()).select_from(AgentTask).where(AgentTask.run_id == ws.run_id)
            )
        ).scalar_one()
        if count >= MAX_BOARD_TASKS:
            raise ToolError(
                f"the board already has {count} tasks (cap {MAX_BOARD_TASKS}) — "
                "finish existing work instead of adding more"
            )
        next_sequence = (
            (
                await db.execute(
                    select(func.max(AgentTask.sequence)).where(AgentTask.run_id == ws.run_id)
                )
            ).scalar_one()
            or 0
        ) + 1
        task = AgentTask(
            run_id=ws.run_id,
            sequence=next_sequence,
            role=role,
            title=title[:256],
            description=description.strip() or None,
        )
        db.add(task)
        db.add(
            AgentEvent(
                run_id=ws.run_id,
                task_id=task.id,
                agent=role,
                type="task.created",
                payload={"sequence": next_sequence, "title": task.title, "role": role},
            )
        )
        await db.commit()
    return f"added task #{next_sequence} ({role}): {task.title}"


async def update_task_status(ws: Workspace, sequence: int, status: str, reason: str = "") -> str:
    """Mark a pending task skipped — the only transition agents get; every
    other status belongs to the runner and supervisor. Skipping a task that
    unfinished work depends on is refused: a skipped dependency can never
    become done, so its dependents would deadlock the board."""
    if status != TaskStatus.SKIPPED:
        raise ToolError(f"agents may only set status '{TaskStatus.SKIPPED}', not {status!r}")
    async with session_scope() as db:
        rows = (
            (await db.execute(select(AgentTask).where(AgentTask.run_id == ws.run_id)))
            .scalars()
            .all()
        )
        task = next((t for t in rows if t.sequence == sequence), None)
        if task is None:
            raise ToolError(f"no task #{sequence} on this run's board")
        if task.status != TaskStatus.PENDING:
            raise ToolError(
                f"task #{sequence} is {task.status} — only pending tasks can be skipped"
            )
        dependents = [
            t.sequence for t in rows if str(task.id) in t.depends_on and t.status in _UNFINISHED
        ]
        if dependents:
            waiting = ", ".join(f"#{s}" for s in sorted(dependents))
            raise ToolError(f"task #{sequence} cannot be skipped — {waiting} still depend(s) on it")
        task.status = TaskStatus.SKIPPED
        task.result = reason.strip() or None
        db.add(
            AgentEvent(
                run_id=ws.run_id,
                task_id=task.id,
                type="task.status_changed",
                payload={
                    "from": TaskStatus.PENDING,
                    "to": TaskStatus.SKIPPED,
                    "title": task.title,
                    "reason": reason.strip()[:300],
                },
            )
        )
        await db.commit()
    return f"skipped task #{sequence}: {task.title}"


async def git_commit(ws: Workspace, message: str) -> str:
    if not message.strip():
        raise ToolError("commit message is empty")
    try:
        await run_git(ws.path, "add", "-A")
        status = await run_git(ws.path, "status", "--porcelain")
        if not status:
            raise ToolError("nothing to commit — no files changed")
        await run_git(ws.path, "commit", "-m", message.strip())
        sha = await run_git(ws.path, "rev-parse", "--short", "HEAD")
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc
    return f"committed {sha}: {message.strip().splitlines()[0]}"


async def git_diff(ws: Workspace) -> str:
    """Everything the agents changed since the clone (committed or not)."""
    try:
        return await run_git(ws.path, "diff", ws.base_sha) or "(no changes yet)"
    except WorkspaceError as exc:
        raise ToolError(str(exc)) from exc


def _safe(ws: Workspace, path: str):
    try:
        return resolve_inside(ws.path, path)
    except JailViolation as exc:
        raise ToolError(f"path not allowed: {exc}") from exc


def _schema(name: str, description: str, params: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": params, "required": required},
        },
    }


_PATH = {"type": "string", "description": "Path relative to the workspace root, e.g. src/app.py"}

TOOLS: dict[str, tuple[Any, dict]] = {
    "list_dir": (
        list_dir,
        _schema(
            "list_dir",
            "List the files and folders at a path in the workspace.",
            {"path": {**_PATH, "description": "Folder to list; '.' for the root."}},
            [],
        ),
    ),
    "read_file": (
        read_file,
        _schema("read_file", "Read one file's full content.", {"path": _PATH}, ["path"]),
    ),
    "search": (
        search,
        _schema(
            "search",
            "Find lines containing a text (case-insensitive) across the workspace.",
            {
                "text": {"type": "string", "description": "Plain text to look for."},
                "path": {**_PATH, "description": "Folder to search in; '.' for everything."},
            },
            ["text"],
        ),
    ),
    "search_code": (
        search_code,
        _schema(
            "search_code",
            "Find code by meaning in the repository's semantic index. Best for "
            "'where is X handled?' questions when you do not know the exact "
            "words; results are from the last indexed snapshot, so use "
            "'search' to verify fresh edits.",
            {
                "query": {
                    "type": "string",
                    "description": "What you are looking for, in plain words.",
                }
            },
            ["query"],
        ),
    ),
    "write_file": (
        write_file,
        _schema(
            "write_file",
            "Create or completely replace one file with the given content. "
            "For small edits to an existing file, prefer apply_patch.",
            {
                "path": _PATH,
                "content": {"type": "string", "description": "The file's entire new content."},
            },
            ["path", "content"],
        ),
    ),
    "apply_patch": (
        apply_patch,
        _schema(
            "apply_patch",
            "Apply a unified diff to the workspace — the right tool for "
            "small edits to existing files (write_file rewrites the whole "
            "file). Include a few unchanged context lines around each "
            "change. If it does not apply, read the file again and "
            "regenerate the diff.",
            {
                "patch": {
                    "type": "string",
                    "description": "A unified diff (---/+++ headers, @@ hunks).",
                }
            },
            ["patch"],
        ),
    ),
    "git_commit": (
        git_commit,
        _schema(
            "git_commit",
            "Commit every change made so far with a message.",
            {"message": {"type": "string", "description": "Short commit message."}},
            ["message"],
        ),
    ),
    "git_diff": (
        git_diff,
        _schema("git_diff", "Show everything changed since the run started.", {}, []),
    ),
    "add_task": (
        add_task,
        _schema(
            "add_task",
            "Add a newly discovered task to this run's board instead of "
            "widening your own diff. It runs after your current task.",
            {
                "title": {"type": "string", "description": "Short imperative title."},
                "description": {
                    "type": "string",
                    "description": "What needs doing and why (optional).",
                },
                "role": {
                    "type": "string",
                    "enum": list(_TASK_ROLES),
                    "description": "Which engineer should take it.",
                },
            },
            ["title"],
        ),
    ),
    "update_task_status": (
        update_task_status,
        _schema(
            "update_task_status",
            "Skip a pending task that turned out to be unnecessary. Give the "
            "reason — it shows on the board in place of a result.",
            {
                "sequence": {"type": "integer", "description": "The task number to skip."},
                "status": {
                    "type": "string",
                    "enum": [str(TaskStatus.SKIPPED)],
                    "description": "Only 'skipped' is allowed.",
                },
                "reason": {"type": "string", "description": "Why the task is unnecessary."},
            },
            ["sequence", "status"],
        ),
    ),
}


def schemas_for(tool_names: tuple[str, ...] | list[str]) -> list[dict]:
    """The JSON schemas an agent's allowed tools — what the model gets to see."""
    return [TOOLS[name][1] for name in tool_names if name in TOOLS]


async def call_tool(ws: Workspace, allowed: tuple[str, ...], name: str, args: dict) -> str:
    """Run one tool call from an agent. Never raises for agent mistakes —
    the error text goes back to the model so it can correct itself."""
    if name not in allowed or name not in TOOLS:
        return f"ERROR: tool {name!r} is not available to you"
    func = TOOLS[name][0]
    try:
        return await func(ws, **args)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"
