"""Retrieval evaluation: does hybrid search beat a plain keyword baseline?

A small golden question set over the fixture service pairs each question with
the file that should answer it. For every question we run hybrid retrieval and
a grep-style keyword baseline, then record where the right file lands (its rank,
if in the top results). The phase exit criterion is hybrid scoring at least as
well as grep on recall and mean reciprocal rank.

Offline (LLM_FAKE=1) the vector arm is noise, so the numbers really measure the
full-text arm plus the fusion mechanics; a real embedding model shows the
semantic lift over grep. Design note: docs/architecture/HYBRID_RETRIEVAL.md.
"""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from engine.indexing.chunker import chunk_repository
from engine.indexing.retrieval import RETRIEVAL_LIMIT, retrieve_chunks

FIXTURE_DIR = Path(__file__).resolve().parents[4] / "fixtures" / "demo-service"

_WORD = re.compile(r"[A-Za-z0-9_]+")

GOLDEN_QUESTIONS: tuple[dict[str, str], ...] = (
    {"question": "return a 404 when the item is not found", "expect": "app/main.py"},
    {"question": "the settings dataclass for the service", "expect": "app/config.py"},
    {"question": "fetch the items and show them on the page", "expect": "web/app.js"},
    {"question": "regression test that an unknown item is 404", "expect": "tests/test_app.py"},
    {"question": "how to install and run the service with uvicorn", "expect": "README.md"},
)


@dataclass
class QuestionScore:
    question: str
    expect: str
    hybrid_rank: int | None  # 1-based rank of the expected file, None if absent
    grep_rank: int | None


@dataclass
class Scorecard:
    rows: list[QuestionScore] = field(default_factory=list)

    def _recall(self, hybrid: bool) -> float:
        hits = sum(1 for row in self.rows if self._rank(row, hybrid) is not None)
        return hits / len(self.rows) if self.rows else 0.0

    def _mrr(self, hybrid: bool) -> float:
        total = sum(
            1.0 / rank for row in self.rows if (rank := self._rank(row, hybrid)) is not None
        )
        return total / len(self.rows) if self.rows else 0.0

    @staticmethod
    def _rank(row: QuestionScore, hybrid: bool) -> int | None:
        return row.hybrid_rank if hybrid else row.grep_rank

    @property
    def hybrid_recall(self) -> float:
        return self._recall(hybrid=True)

    @property
    def grep_recall(self) -> float:
        return self._recall(hybrid=False)

    @property
    def hybrid_mrr(self) -> float:
        return self._mrr(hybrid=True)

    @property
    def grep_mrr(self) -> float:
        return self._mrr(hybrid=False)


def grep_baseline(root: Path, question: str, limit: int = RETRIEVAL_LIMIT) -> list[str]:
    """Rank files by how many of the question's distinct words appear as
    substrings — a fair, strong stand-in for keyword search."""
    words = set(_WORD.findall(question.lower()))
    text_by_path: dict[str, str] = {}
    for chunk in chunk_repository(root):
        text_by_path[chunk.path] = text_by_path.get(chunk.path, "") + "\n" + chunk.content.lower()
    scored = [(sum(word in text for word in words), path) for path, text in text_by_path.items()]
    scored = [pair for pair in scored if pair[0] > 0]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [path for _, path in scored[:limit]]


def _rank_of(path: str, ordered_paths: list[str]) -> int | None:
    for position, candidate in enumerate(ordered_paths, start=1):
        if candidate == path:
            return position
    return None


def _dedupe(paths: list[str]) -> list[str]:
    """Chunk paths collapsed to their first appearance — file-level ranking."""
    seen: list[str] = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return seen


async def evaluate_retrieval(
    db: AsyncSession, repository_id: uuid.UUID, root: Path = FIXTURE_DIR
) -> Scorecard:
    """Score hybrid retrieval and the grep baseline on every golden question."""
    card = Scorecard()
    for golden in GOLDEN_QUESTIONS:
        question, expect = golden["question"], golden["expect"]
        chunks = await retrieve_chunks(db, repository_id, question)
        hybrid_paths = _dedupe([chunk.path for chunk in chunks])
        grep_paths = grep_baseline(root, question)
        card.rows.append(
            QuestionScore(
                question=question,
                expect=expect,
                hybrid_rank=_rank_of(expect, hybrid_paths),
                grep_rank=_rank_of(expect, grep_paths),
            )
        )
    return card
