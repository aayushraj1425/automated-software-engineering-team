"""Chunker behavior and the repository index/search API (offline embeddings).

Fake embeddings are deterministic — identical text gets an identical vector —
so searching with a file's exact content must rank that file's chunk first
with a near-perfect score.
"""

import uuid

from engine.evaluation import FIXTURE_DIR, prepare_fixture_repo
from engine.indexing.chunker import CHUNK_LINES, chunk_repository
from tests.conftest import auth_headers


def test_chunker_windows_languages_and_skips(tmp_path):
    (tmp_path / "big.py").write_text("\n".join(f"line {i}" for i in range(1, 131)))
    (tmp_path / "notes.md").write_text("# hello\n")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("module.exports = 1;")

    chunks = chunk_repository(tmp_path)

    paths = {chunk.path for chunk in chunks}
    assert paths == {"big.py", "notes.md"}  # binaries and node_modules skipped
    big = [chunk for chunk in chunks if chunk.path == "big.py"]
    # No definitions in this file, so it falls back to overlapping line windows.
    assert [chunk.start_line for chunk in big] == [1, 51, 101]
    assert big[0].end_line == CHUNK_LINES
    assert big[0].language == "python"


def test_ast_chunker_keeps_python_functions_whole(tmp_path):
    lines = ["import os", ""]
    lines += ["def alpha():"] + [f"    a = {i}" for i in range(40)]  # lines 3..43
    lines += ["", "def beta():"] + [f"    b = {i}" for i in range(40)]  # lines 45..85
    (tmp_path / "svc.py").write_text("\n".join(lines))

    chunks = chunk_repository(tmp_path)
    by_start = {chunk.start_line: chunk for chunk in chunks}

    # Each function is one chunk at its real boundary — not cut at line 60.
    assert 3 in by_start and by_start[3].content.startswith("def alpha():")
    assert by_start[3].end_line == 43 and "a = 39" in by_start[3].content
    assert 45 in by_start and by_start[45].content.startswith("def beta():")
    assert "b = 39" in by_start[45].content
    # The imports before the first definition are their own (windowed) chunk.
    assert by_start[1].content == "import os"


def test_ast_chunker_splits_javascript_exports(tmp_path):
    lines = ["import x from 'y'", ""]
    lines += ["export function foo() {"] + [f"  const a{i} = {i};" for i in range(40)] + ["}"]
    lines += ["", "function bar() {"] + [f"  const b{i} = {i};" for i in range(20)] + ["}"]
    (tmp_path / "app.js").write_text("\n".join(lines))

    chunks = chunk_repository(tmp_path)
    contents = [chunk.content for chunk in chunks]

    assert any(c.startswith("export function foo()") for c in contents)
    assert any(c.startswith("function bar()") for c in contents)
    # foo is kept whole rather than sliced into a blind 60-line window.
    foo = next(chunk for chunk in chunks if chunk.content.startswith("export function foo()"))
    assert foo.start_line == 3 and "const a39 = 39;" in foo.content


async def test_connect_index_and_search(client, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    headers = auth_headers(f"user_{uuid.uuid4().hex[:8]}")

    created = await client.post("/v1/repositories", json={"url": str(origin)}, headers=headers)
    assert created.status_code == 201
    repo = created.json()
    assert repo["chunks"] == 0

    started = await client.post(f"/v1/repositories/{repo['id']}/index", headers=headers)
    assert started.status_code == 202
    # httpx's ASGI transport waits for background tasks — indexing is done here
    listed = (await client.get("/v1/repositories", headers=headers)).json()
    assert listed[0]["status"] == "indexed"
    assert listed[0]["chunks"] > 0
    assert listed[0]["last_indexed_at"] is not None

    raw = (FIXTURE_DIR / "app" / "config.py").read_text(encoding="utf-8")
    query = "\n".join(raw.splitlines()).strip()
    hits = (
        await client.get(
            f"/v1/repositories/{repo['id']}/search", params={"q": query}, headers=headers
        )
    ).json()
    assert hits[0]["path"] == "app/config.py"
    assert hits[0]["score"] > 0.99
    assert hits[0]["start_line"] == 1


async def test_repository_dependency_graph(client, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    headers = auth_headers(f"user_{uuid.uuid4().hex[:8]}")

    repo = (
        await client.post("/v1/repositories", json={"url": str(origin)}, headers=headers)
    ).json()
    await client.post(f"/v1/repositories/{repo['id']}/index", headers=headers)

    graph = (await client.get(f"/v1/repositories/{repo['id']}/graph", headers=headers)).json()
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("app/main.py", "app/config.py") in edges
    assert ("tests/test_app.py", "app/main.py") in edges

    node_paths = {node["path"] for node in graph["nodes"]}
    assert {"app/main.py", "app/config.py", "tests/test_app.py"} <= node_paths
    main = next(node for node in graph["nodes"] if node["path"] == "app/main.py")
    assert main["in_degree"] == 1  # imported by the test
    assert main["out_degree"] == 1  # imports the config


async def test_graph_is_owner_scoped(client, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    owner = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    intruder = auth_headers(f"user_{uuid.uuid4().hex[:8]}")

    repo = (await client.post("/v1/repositories", json={"url": str(origin)}, headers=owner)).json()
    denied = await client.get(f"/v1/repositories/{repo['id']}/graph", headers=intruder)
    assert denied.status_code == 404


async def test_repositories_are_owner_scoped(client, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    owner = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    intruder = auth_headers(f"user_{uuid.uuid4().hex[:8]}")

    repo = (await client.post("/v1/repositories", json={"url": str(origin)}, headers=owner)).json()

    assert (await client.get("/v1/repositories", headers=intruder)).json() == []
    denied = await client.post(f"/v1/repositories/{repo['id']}/index", headers=intruder)
    assert denied.status_code == 404
    denied = await client.get(
        f"/v1/repositories/{repo['id']}/search", params={"q": "anything"}, headers=intruder
    )
    assert denied.status_code == 404
