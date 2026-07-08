"""Hybrid retrieval and the retrieval evaluation (offline embeddings).

The full-text arm needs no model, so even offline a keyword query must find
the file that literally contains the words. The evaluation harness compares
hybrid retrieval to a grep baseline on the golden question set.
"""

import uuid

from engine.db.session import session_scope
from engine.evaluation import FIXTURE_DIR, prepare_fixture_repo
from engine.indexing.retrieval import retrieve_chunks
from engine.retrieval_eval import GOLDEN_QUESTIONS, evaluate_retrieval, grep_baseline
from tests.conftest import auth_headers


async def _index_fixture(client, tmp_path) -> uuid.UUID:
    origin = prepare_fixture_repo(tmp_path / "origin")
    headers = auth_headers(f"user_{uuid.uuid4().hex[:8]}")
    repo = (
        await client.post("/v1/repositories", json={"url": str(origin)}, headers=headers)
    ).json()
    started = await client.post(f"/v1/repositories/{repo['id']}/index", headers=headers)
    assert started.status_code == 202  # background indexing completes under ASGI transport
    return uuid.UUID(repo["id"])


def test_grep_baseline_ranks_the_keyword_file_first():
    ranked = grep_baseline(FIXTURE_DIR, "the settings dataclass for the service")
    assert ranked[0] == "app/config.py"


async def test_hybrid_search_finds_a_keyword_match(client, tmp_path):
    repository_id = await _index_fixture(client, tmp_path)
    async with session_scope() as db:
        hits = await retrieve_chunks(db, repository_id, "settings dataclass service")
    assert any(hit.path == "app/config.py" for hit in hits)


async def test_hybrid_scores_at_least_as_well_as_grep(client, tmp_path):
    repository_id = await _index_fixture(client, tmp_path)
    async with session_scope() as db:
        card = await evaluate_retrieval(db, repository_id)

    assert len(card.rows) == len(GOLDEN_QUESTIONS)
    assert card.hybrid_recall == 1.0  # every expected file surfaces in the top results
    assert card.hybrid_recall >= card.grep_recall
    assert card.hybrid_mrr > 0.0
