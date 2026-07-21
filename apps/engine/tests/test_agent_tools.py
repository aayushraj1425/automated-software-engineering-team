"""The toolbox: jailed file access, search, git, and the dispatcher."""

import subprocess
import uuid

import pytest

from engine.agents.tools import (
    ToolError,
    apply_patch,
    call_tool,
    git_commit,
    git_diff,
    list_dir,
    read_file,
    schemas_for,
    search,
    search_code,
    write_file,
)
from engine.db.enums import RunStatus
from engine.db.models import AgentRun, CodeChunk, Repository
from engine.db.session import session_scope
from engine.llm.router import model_router
from engine.workspace.manager import Workspace


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def ws(tmp_path) -> Workspace:
    """A workspace over a real mini git repo (local, no network)."""
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@test.local")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def greet():\n    return 'hello world'\n")
    (repo / "README.md").write_text("# Demo\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    return Workspace(run_id=uuid.uuid4(), path=repo, branch="asep/run-test", base_sha=base)


async def test_list_read_and_search(ws):
    listing = await list_dir(ws)
    assert "dir  src" in listing and "file README.md" in listing and ".git" not in listing

    content = await read_file(ws, "src/app.py")
    assert "hello world" in content

    hits = await search(ws, "HELLO")
    assert hits == "src/app.py:2: return 'hello world'"


def _find_ripgrep() -> str | None:
    """rg from PATH, or VS Code's bundled copy on a dev machine without one."""
    import glob
    import os

    found = __import__("shutil").which("rg")
    if found:
        return found
    for pattern in (
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\**\rg.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\**\rg.exe"),
    ):
        hits = glob.glob(pattern, recursive=True)
        if hits:
            return hits[0]
    return None


async def test_search_engines_agree(ws, monkeypatch):
    """Both engines honor the same output contract (RIPGREP_SEARCH.md)."""
    import engine.agents.tools as tools_module

    monkeypatch.setattr(tools_module.shutil, "which", lambda _name: None)
    fallback = await search(ws, "HELLO")
    assert fallback == "src/app.py:2: return 'hello world'"

    ripgrep = _find_ripgrep()
    if ripgrep is None:
        pytest.skip("ripgrep not installed on this machine")
    monkeypatch.setattr(tools_module.shutil, "which", lambda _name: ripgrep)
    fast = await search(ws, "HELLO")
    assert fast == fallback

    assert await search(ws, "nothing says this") == "no matches for 'nothing says this'"


async def test_write_creates_folders_and_diff_sees_it(ws):
    await write_file(ws, "src/api/status.py", "STATUS = 'ok'\n")
    assert (ws.path / "src" / "api" / "status.py").read_text() == "STATUS = 'ok'\n"

    result = await git_commit(ws, "add status module")
    assert result.startswith("committed ")

    diff = await git_diff(ws)
    assert "+STATUS = 'ok'" in diff


async def test_tools_refuse_jail_escapes(ws):
    for bad in ("../secret.txt", "C:\\Windows\\hosts", "..\\..\\x"):
        with pytest.raises(ToolError):
            await read_file(ws, bad)
        with pytest.raises(ToolError):
            await write_file(ws, bad, "x")


async def test_read_limits_and_missing_files(ws):
    with pytest.raises(ToolError):
        await read_file(ws, "nope.py")
    (ws.path / "big.bin").write_text("x" * 70_000)
    with pytest.raises(ToolError):
        await read_file(ws, "big.bin")


async def test_git_commit_with_nothing_to_commit(ws):
    with pytest.raises(ToolError):
        await git_commit(ws, "empty commit")


async def test_call_tool_enforces_the_allow_list(ws):
    allowed = ("read_file", "list_dir")
    ok = await call_tool(ws, allowed, "read_file", {"path": "README.md"})
    assert ok == "# Demo\n"

    denied = await call_tool(ws, allowed, "write_file", {"path": "x.py", "content": "x"})
    assert denied.startswith("ERROR: tool 'write_file' is not available")
    assert not (ws.path / "x.py").exists()

    unknown = await call_tool(ws, allowed, "rm_rf", {})
    assert unknown.startswith("ERROR")


async def test_call_tool_returns_errors_instead_of_raising(ws):
    out = await call_tool(ws, ("read_file",), "read_file", {"path": "../outside"})
    assert out.startswith("ERROR: path not allowed")
    out = await call_tool(ws, ("read_file",), "read_file", {"wrong_arg": "x"})
    assert out.startswith("ERROR: bad arguments")


async def test_search_code_finds_indexed_chunks_by_meaning(ws, prepared_db):
    content = "def list_items():\n    return ITEMS\n"
    (embedding,) = await model_router.embed([content])
    async with session_scope() as db:
        repo = Repository(owner_id="tool-test", url=f"local://{uuid.uuid4().hex[:8]}")
        db.add(repo)
        await db.flush()
        db.add(
            AgentRun(
                id=ws.run_id,
                user_id="tool-test",
                repository_id=repo.id,
                request="test",
                status=RunStatus.EXECUTING,
            )
        )
        db.add(
            CodeChunk(
                repository_id=repo.id,
                path="app/items.py",
                language="python",
                start_line=1,
                end_line=2,
                content=content,
                embedding=embedding,
            )
        )
        await db.commit()

    # Fake embeddings are deterministic: identical text is the closest match.
    out = await search_code(ws, content)
    first_line = out.splitlines()[0]
    assert first_line.startswith("app/items.py:1-2")
    assert "score" in first_line
    assert "return ITEMS" in out


async def test_search_code_without_an_index_guides_the_agent(ws, prepared_db):
    # The ws fixture's run id has no AgentRun row — same answer as no index.
    out = await search_code(ws, "where is authentication handled?")
    assert not out.startswith("ERROR")
    assert "'search'" in out

    with pytest.raises(ToolError):
        await search_code(ws, "   ")


def test_schemas_only_cover_implemented_tools():
    # Unknown names are dropped, not offered — the registry test asserts no
    # declared name is ever unknown, so this guards runtime inputs only.
    schemas = schemas_for(("read_file", "brew_coffee", "apply_patch", "git_diff"))
    names = [s["function"]["name"] for s in schemas]
    assert names == ["read_file", "apply_patch", "git_diff"]


# ── apply_patch: the edit is the size of the change ─────────────────────────


async def test_apply_patch_modifies_a_file_with_git_prefixes(ws):
    patch = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'hello world'\n"
        "+    return 'hello patch'\n"
    )
    out = await apply_patch(ws, patch)
    assert out == "patched 1 file(s): src/app.py"
    assert "hello patch" in (ws.path / "src" / "app.py").read_text()


async def test_apply_patch_accepts_bare_paths_too(ws):
    patch = (
        "--- src/app.py\n"
        "+++ src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'hello world'\n"
        "+    return 'hello p0'\n"
    )
    await apply_patch(ws, patch)
    assert "hello p0" in (ws.path / "src" / "app.py").read_text()


async def test_apply_patch_creates_a_new_file(ws):
    patch = "--- /dev/null\n+++ b/docs/note.md\n@@ -0,0 +1,2 @@\n+# Note\n+patched into being\n"
    out = await apply_patch(ws, patch)
    assert "docs/note.md" in out
    assert (ws.path / "docs" / "note.md").read_text() == "# Note\npatched into being\n"


async def test_apply_patch_refuses_jail_escapes(ws):
    patch = "--- /dev/null\n+++ b/../escape.txt\n@@ -0,0 +1 @@\n+nope\n"
    with pytest.raises(ToolError, match="path not allowed"):
        await apply_patch(ws, patch)
    assert not (ws.path.parent / "escape.txt").exists()


async def test_apply_patch_mismatch_asks_for_a_regenerated_diff(ws):
    patch = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def greet():\n"
        "-    return 'something the file never said'\n"
        "+    return 'x'\n"
    )
    with pytest.raises(ToolError, match="regenerate the diff"):
        await apply_patch(ws, patch)
    assert "hello world" in (ws.path / "src" / "app.py").read_text()  # untouched


async def test_apply_patch_rejects_non_diffs(ws):
    with pytest.raises(ToolError, match="not a unified diff"):
        await apply_patch(ws, "please change the greeting to hello")
