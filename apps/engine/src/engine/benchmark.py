"""Performance baselines for the hot paths, measured offline.

Three measurements through the real code paths with the fake model and fake
embeddings, so the numbers isolate our machinery (chunking, Postgres,
workspace git) rather than a provider's latency:

    uv run python -m engine.benchmark              # all three
    uv run python -m engine.benchmark indexing --files 120
    uv run python -m engine.benchmark retrieval --repeats 10
    uv run python -m engine.benchmark run-pipeline

Baselines are recorded in docs/architecture/BENCHMARKS.md — rerun after any
change that touches these paths and update the table in the same PR.
"""

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from engine.config import get_settings
from engine.db.session import session_scope
from engine.evaluation import GOLDEN_TASKS, prepare_fixture_repo, run_golden_task
from engine.indexing.indexer import index_repository
from engine.indexing.retrieval import retrieve_chunks
from engine.retrieval_eval import GOLDEN_QUESTIONS
from engine.workspace.manager import remove_tree

BENCH_OWNER = "benchmark-harness"


@dataclass
class IndexingBaseline:
    files: int
    chunks: int
    full_seconds: float
    noop_seconds: float  # second pass over the unchanged repo (incremental)

    @property
    def files_per_second(self) -> float:
        return self.files / self.full_seconds if self.full_seconds else 0.0

    @property
    def chunks_per_second(self) -> float:
        return self.chunks / self.full_seconds if self.full_seconds else 0.0


@dataclass
class RetrievalBaseline:
    queries: int
    p50_ms: float
    p95_ms: float


@dataclass
class RunPipelineBaseline:
    task: str
    completed: bool
    total_seconds: float


def _synthesize_repository(root: Path, files: int) -> None:
    """N plausible Python modules — imports, a class, functions — so the
    tree-sitter chunker produces realistic chunk counts."""
    package = root / "service"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    for index in range(files):
        module = "\n".join(
            [
                f'"""Module {index} of the synthetic benchmark corpus."""',
                "",
                "from dataclasses import dataclass",
                "",
                "",
                "@dataclass",
                f"class Record{index}:",
                "    name: str",
                "    value: int = 0",
                "",
                "",
                f"def load_record_{index}(name: str) -> Record{index}:",
                '    """Build a record for the given name."""',
                f"    return Record{index}(name=name, value={index})",
                "",
                "",
                f"def summarize_{index}(records: list) -> dict:",
                "    total = sum(record.value for record in records)",
                '    return {"count": len(records), "total": total}',
                "",
            ]
        )
        (package / f"module_{index:04d}.py").write_text(module)


async def _register_repository(origin: Path) -> uuid.UUID:
    from engine.db.models import Repository

    async with session_scope() as session:
        repo = Repository(owner_id=BENCH_OWNER, url=str(origin))
        session.add(repo)
        await session.commit()
        return repo.id


async def _drop_repository(repository_id: uuid.UUID) -> None:
    """Benchmarks tidy up after themselves — the dev database should not
    accumulate synthetic corpora (chunks/edges cascade with the row)."""
    from engine.db.models import Repository

    async with session_scope() as session:
        repo = await session.get(Repository, repository_id)
        if repo is not None:
            await session.delete(repo)
            await session.commit()


async def _count_chunks(repository_id: uuid.UUID) -> int:
    from sqlalchemy import func, select

    from engine.db.models import CodeChunk

    async with session_scope() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(CodeChunk)
                .where(CodeChunk.repository_id == repository_id)
            )
        ).scalar_one()


async def benchmark_indexing(files: int) -> IndexingBaseline:
    """Index a synthetic N-file repository, then re-index it unchanged."""
    tmp = Path(tempfile.mkdtemp(prefix="asep-bench-index-"))
    try:
        origin = tmp / "corpus"
        origin.mkdir()
        _synthesize_repository(origin, files)
        _git_commit_all(origin)
        repository_id = await _register_repository(origin)
        try:
            started = time.perf_counter()
            await index_repository(repository_id)
            full_seconds = time.perf_counter() - started

            started = time.perf_counter()
            await index_repository(repository_id)  # nothing changed — incremental no-op
            noop_seconds = time.perf_counter() - started

            chunks = await _count_chunks(repository_id)
        finally:
            await _drop_repository(repository_id)
        return IndexingBaseline(
            files=files + 1,  # __init__.py rides along
            chunks=chunks,
            full_seconds=full_seconds,
            noop_seconds=noop_seconds,
        )
    finally:
        remove_tree(tmp)


async def benchmark_retrieval(repeats: int) -> RetrievalBaseline:
    """Hybrid retrieval latency over the indexed fixture service."""
    tmp = Path(tempfile.mkdtemp(prefix="asep-bench-retrieval-"))
    try:
        origin = prepare_fixture_repo(tmp / "fixture")
        repository_id = await _register_repository(origin)
        latencies_ms: list[float] = []
        try:
            await index_repository(repository_id)
            async with session_scope() as session:
                for _ in range(repeats):
                    for golden in GOLDEN_QUESTIONS:
                        started = time.perf_counter()
                        await retrieve_chunks(session, repository_id, golden["question"])
                        latencies_ms.append((time.perf_counter() - started) * 1000)
        finally:
            await _drop_repository(repository_id)

        latencies_ms.sort()
        return RetrievalBaseline(
            queries=len(latencies_ms),
            p50_ms=statistics.median(latencies_ms),
            p95_ms=latencies_ms[max(0, round(0.95 * len(latencies_ms)) - 1)],
        )
    finally:
        remove_tree(tmp)


async def benchmark_run_pipeline() -> RunPipelineBaseline:
    """One golden task through plan → approve → execute → review, fake model.

    The fake model answers instantly, so this measures the platform's own
    overhead: DB round-trips, workspace git operations, event writes.
    """
    golden = GOLDEN_TASKS[0]
    tmp = Path(tempfile.mkdtemp(prefix="asep-bench-run-"))
    try:
        origin = prepare_fixture_repo(tmp / "fixture")
        started = time.perf_counter()
        score = await run_golden_task(origin, golden)
        total_seconds = time.perf_counter() - started
        return RunPipelineBaseline(
            task=golden["name"], completed=score.passed, total_seconds=total_seconds
        )
    finally:
        remove_tree(tmp)


def _git_commit_all(root: Path) -> None:
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    _git("init", "--initial-branch=main")
    _git("config", "user.name", "Benchmark Harness")
    _git("config", "user.email", "benchmark@asep.local")
    _git("add", ".")
    _git("commit", "-m", "synthetic benchmark corpus")


def _print_indexing(result: IndexingBaseline) -> None:
    print(
        # ASCII only: Windows consoles often default to cp1252
        f"indexing      {result.files} files, {result.chunks} chunks in "
        f"{result.full_seconds:.2f}s "
        f"({result.files_per_second:.1f} files/s, {result.chunks_per_second:.1f} chunks/s); "
        f"unchanged re-index {result.noop_seconds:.2f}s"
    )


def _print_retrieval(result: RetrievalBaseline) -> None:
    print(
        f"retrieval     {result.queries} hybrid queries: "
        f"p50 {result.p50_ms:.1f} ms, p95 {result.p95_ms:.1f} ms"
    )


def _print_run(result: RunPipelineBaseline) -> None:
    status = "completed" if result.completed else "FAILED"
    print(f"run pipeline  '{result.task}' {status} in {result.total_seconds:.2f}s (fake model)")


async def _run(args: argparse.Namespace) -> int:
    if args.command in (None, "indexing"):
        _print_indexing(await benchmark_indexing(args.files))
    if args.command in (None, "retrieval"):
        _print_retrieval(await benchmark_retrieval(args.repeats))
    if args.command in (None, "run-pipeline"):
        result = await benchmark_run_pipeline()
        _print_run(result)
        if not result.completed:
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m engine.benchmark",
        description="Offline performance baselines (docs/architecture/BENCHMARKS.md)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["indexing", "retrieval", "run-pipeline"],
        help="one measurement; omit to run all three",
    )
    parser.add_argument("--files", type=int, default=120, help="synthetic corpus size")
    parser.add_argument("--repeats", type=int, default=10, help="passes over the question set")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.llm_fake:
        print("benchmarks run offline: set LLM_FAKE=1 (real models measure the provider, not us)")
        return 2

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
