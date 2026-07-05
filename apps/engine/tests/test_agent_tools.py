"""The toolbox: jailed file access, search, git, and the dispatcher."""

import subprocess
import uuid

import pytest

from engine.agents.tools import (
    ToolError,
    call_tool,
    git_commit,
    git_diff,
    list_dir,
    read_file,
    schemas_for,
    search,
    write_file,
)
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


def test_schemas_only_cover_implemented_tools():
    schemas = schemas_for(("read_file", "apply_patch", "git_diff"))
    names = [s["function"]["name"] for s in schemas]
    assert names == ["read_file", "git_diff"]  # apply_patch not built yet
