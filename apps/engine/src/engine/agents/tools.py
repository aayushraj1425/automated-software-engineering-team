"""The agents' toolbox: read, write, search, and git — all inside the jail.

Each tool is an async function plus a JSON schema (the part the AI model
sees). call_tool() is the single dispatcher: it checks the tool is on the
agent's allow-list (deny by default, per the registry), runs it, and turns
any ToolError into a plain error message the agent can read and react to.
Every path an agent supplies goes through the jail before anything is touched.
"""

from typing import Any

from engine.workspace.jail import JailViolation, resolve_inside
from engine.workspace.manager import Workspace, WorkspaceError, run_git

MAX_READ_BYTES = 64_000
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 50
MAX_SEARCH_FILE_BYTES = 512_000


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


async def search(ws: Workspace, text: str, path: str = ".") -> str:
    """Case-insensitive plain-text search across the workspace files."""
    if not text.strip():
        raise ToolError("search text is empty")
    root = _safe(ws, path)
    needle = text.lower()
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
    "write_file": (
        write_file,
        _schema(
            "write_file",
            "Create or completely replace one file with the given content.",
            {
                "path": _PATH,
                "content": {"type": "string", "description": "The file's entire new content."},
            },
            ["path", "content"],
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
