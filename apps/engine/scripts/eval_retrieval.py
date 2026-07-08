"""Index the fixture service and score hybrid retrieval against a grep baseline.

Usage, inside apps/engine (Postgres must be running — `pnpm db:up`):

    uv run python scripts/eval_retrieval.py

With LLM_FAKE=1 the vector arm is noise, so the score reflects the full-text
arm plus fusion; a real embedding model shows the semantic lift over grep.
Exit code 0 means hybrid did at least as well as grep on recall and MRR.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# psycopg async cannot run on Windows' default ProactorEventLoop, and the
# cp1252 console cannot print em dashes — force UTF-8.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from engine.config import get_settings  # noqa: E402
from engine.db.models import Repository  # noqa: E402
from engine.db.session import session_scope  # noqa: E402
from engine.evaluation import prepare_fixture_repo  # noqa: E402
from engine.indexing.indexer import index_repository  # noqa: E402
from engine.retrieval_eval import evaluate_retrieval  # noqa: E402


def _rank(value: int | None) -> str:
    return f"#{value}" if value is not None else "—"


async def main() -> int:
    mode = "offline (LLM_FAKE=1)" if get_settings().llm_fake else "real model"
    print(f"Retrieval evaluation — {mode}\n")

    with tempfile.TemporaryDirectory(prefix="asep-retrieval-eval-") as tmp:
        origin = prepare_fixture_repo(Path(tmp) / "origin")
        async with session_scope() as session:
            repo = Repository(owner_id="eval-harness", url=str(origin))
            session.add(repo)
            await session.commit()
            repository_id = repo.id
        await index_repository(repository_id)
        async with session_scope() as session:
            card = await evaluate_retrieval(session, repository_id)
    return _report(card)


def _report(card) -> int:
    for row in card.rows:
        agree = row.hybrid_rank is not None
        verdict = "FOUND" if agree else "MISS "
        print(
            f"  [{verdict}] {row.expect}\n"
            f"         hybrid {_rank(row.hybrid_rank)} · grep {_rank(row.grep_rank)}"
            f"   ({row.question})"
        )
    print(
        f"\n  recall  hybrid {card.hybrid_recall:.2f} · grep {card.grep_recall:.2f}"
        f"\n  MRR     hybrid {card.hybrid_mrr:.2f} · grep {card.grep_mrr:.2f}"
    )
    wins = card.hybrid_recall >= card.grep_recall and card.hybrid_mrr >= card.grep_mrr
    print(f"\n  hybrid {'>=' if wins else '<'} grep  →  {'PASS' if wins else 'FAIL'}")
    return 0 if wins else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
