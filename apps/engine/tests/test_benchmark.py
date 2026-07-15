"""The benchmark harness stays runnable — tiny sizes, shape checks only.

Numbers are NOT asserted (timing assertions flake on slow runners); the real
baselines live in docs/architecture/BENCHMARKS.md. The run-pipeline path is
run_golden_task, which the evaluation tests already exercise end to end.
"""

from sqlalchemy import func, select

from engine.benchmark import BENCH_OWNER, benchmark_indexing, benchmark_retrieval, main
from engine.db.models import Repository
from engine.db.session import session_scope


async def test_indexing_baseline_measures_and_tidies_up(prepared_db):
    result = await benchmark_indexing(files=3)

    assert result.files == 4  # 3 modules + __init__.py
    assert result.chunks > 0
    assert result.full_seconds > 0
    assert result.noop_seconds > 0
    assert result.files_per_second > 0

    async with session_scope() as session:  # the synthetic corpus is gone
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(Repository)
                .where(Repository.owner_id == BENCH_OWNER)
            )
        ).scalar_one()
    assert remaining == 0


async def test_retrieval_baseline_reports_latency_percentiles(prepared_db):
    result = await benchmark_retrieval(repeats=1)

    assert result.queries == 5  # one pass over the golden questions
    assert result.p50_ms > 0
    assert result.p95_ms >= result.p50_ms


def test_cli_refuses_to_run_against_a_real_model(monkeypatch):
    from engine.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_fake", False)
    assert main(["indexing"]) == 2
