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
    assert [chunk.start_line for chunk in big] == [1, 51, 101]  # overlapping windows
    assert big[0].end_line == CHUNK_LINES
    assert big[0].language == "python"


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
