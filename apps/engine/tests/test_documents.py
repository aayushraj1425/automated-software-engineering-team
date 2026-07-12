"""Documentation Suite: generate human-facing docs from the index.

LLM_FAKE=1 (set in conftest) keeps everything offline — the Technical Writer
returns a deterministic document listing the repository's real file paths, so
the whole path (generate → persist → list → delete) runs without a model.
Design note: docs/architecture/DOCUMENTATION_SUITE.md.
"""

import uuid

from engine.db.models import CodeChunk
from engine.db.session import session_scope
from engine.docs.generator import DocumentKind, generate_document
from engine.llm.router import model_router
from tests.conftest import auth_headers


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


def _repo_url() -> str:
    return f"https://github.com/acme/demo-{uuid.uuid4().hex[:8]}"


async def _create_repo(client, headers, url: str | None = None) -> str:
    resp = await client.post("/v1/repositories", json={"url": url or _repo_url()}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _generate(client, headers, repo_id: str, kind: str = "readme") -> dict:
    resp = await client.post(
        f"/v1/repositories/{repo_id}/documents", json={"kind": kind}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _list(client, headers, repo_id: str) -> list[dict]:
    resp = await client.get(f"/v1/repositories/{repo_id}/documents", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_chunk(repo_id: uuid.UUID, path: str, content: str) -> None:
    """Drop one indexed chunk in so the writer has a real file to describe."""
    (embedding,) = await model_router.embed([content])
    async with session_scope() as session:
        session.add(
            CodeChunk(
                repository_id=repo_id,
                path=path,
                language="python",
                start_line=1,
                end_line=content.count("\n") + 1,
                content=content,
                embedding=embedding,
            )
        )
        await session.commit()


# ── The generator, offline ──────────────────────────────────────────────────


async def test_generate_offline_returns_a_titled_document():
    for kind in DocumentKind:
        doc = await generate_document(kind, file_map="src/app.py\nsrc/db.py")
        assert doc["title"]
        assert doc["content"].strip()
        # the offline document grounds itself in the real file map
        assert "src/app.py" in doc["content"]


# ── The API: generate, list, delete ─────────────────────────────────────────


async def test_generate_and_list_a_document(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)

    created = await _generate(client, headers, repo_id, kind="readme")
    assert created["kind"] == "readme"
    assert created["title"] == "README"
    assert created["created_by"]  # stamped with the caller

    listed = await _list(client, headers, repo_id)
    assert [d["id"] for d in listed] == [created["id"]]


async def test_document_is_grounded_in_the_repository_files(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    await _seed_chunk(uuid.UUID(repo_id), "engine/api/documents.py", "def generate(): ...")

    created = await _generate(client, headers, repo_id, kind="architecture")
    assert "engine/api/documents.py" in created["content"]


async def test_documents_are_listed_newest_first(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    first = await _generate(client, headers, repo_id, kind="readme")
    second = await _generate(client, headers, repo_id, kind="changelog")

    listed = await _list(client, headers, repo_id)
    assert [d["id"] for d in listed] == [second["id"], first["id"]]


async def test_documents_are_owner_scoped(client):
    owner = _headers()
    repo_id = await _create_repo(client, owner)
    stranger = _headers()
    resp = await client.get(f"/v1/repositories/{repo_id}/documents", headers=stranger)
    assert resp.status_code == 404


async def test_delete_removes_the_document(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    doc = await _generate(client, headers, repo_id)

    resp = await client.delete(f"/v1/repositories/{repo_id}/documents/{doc['id']}", headers=headers)
    assert resp.status_code == 204
    assert await _list(client, headers, repo_id) == []


async def test_unknown_kind_is_rejected(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    resp = await client.post(
        f"/v1/repositories/{repo_id}/documents", json={"kind": "manifesto"}, headers=headers
    )
    assert resp.status_code == 422
