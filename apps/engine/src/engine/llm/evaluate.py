"""Run the real evaluation for one catalog model and produce signed evidence.

Used by `scripts/eval_open_model.py`. The tool call probes go through the
ModelRouter with the candidate selected, and the golden tasks run through the real
pipeline with every seat pinned to the candidate. Collaborators are injectable so
unit tests can use stub providers; the script uses the real ones.
"""

import tempfile
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.config import Settings
from engine.llm.catalog import ModelEntry, ModelSelection, ModelSelectionError, SeatLevel
from engine.llm.evidence import (
    EvaluationEvidence,
    ProbeEvidence,
    TaskEvidence,
    build_evidence,
)
from engine.llm.probes import Complete, run_probes
from engine.llm.providers import has_credentials
from engine.llm.router import model_router, selected_model_var

EvaluateTeam = Callable[[Path], Awaitable[list[Any]]]


def router_complete(entry: ModelEntry) -> Complete:
    """Probe calls through the ModelRouter with exactly this model selected."""

    async def complete(messages, tools):
        pick = ModelSelection(entry.id, SeatLevel.ENGINEER, SeatLevel.ENGINEER, "evaluation probe")
        token = selected_model_var.set(pick)
        try:
            return await model_router.complete_with_tools("coder", messages, tools)
        finally:
            selected_model_var.reset(token)

    return complete


@contextmanager
def pinned_for_evaluation(settings: Settings, entry: ModelEntry):
    """Make `entry` the only catalog model and pin every seat to it, then restore."""
    saved = settings.model_catalog, settings.model_level_pins
    settings.model_catalog = [entry]
    settings.model_level_pins = {level: entry.id for level in SeatLevel}
    try:
        yield
    finally:
        settings.model_catalog, settings.model_level_pins = saved


def check_ready(entry: ModelEntry, settings: Settings) -> None:
    if settings.llm_fake:
        raise ModelSelectionError("LLM_FAKE is on: an offline run cannot certify a model")
    if not entry.supports_tools:
        raise ModelSelectionError(f"{entry.id} is marked supports_tools=false")
    if not has_credentials(settings, entry):
        raise ModelSelectionError(f"no API key available for {entry.id}")


def task_evidence(scores: list[Any]) -> list[TaskEvidence]:
    return [
        TaskEvidence(
            name=s.name,
            planned=s.planned,
            completed=s.completed,
            committed=s.committed,
            diff_matched=s.diff_matched,
            cost_usd=s.cost_usd,
            error=(s.error or None) and s.error[:300],
        )
        for s in scores
    ]


async def evaluate_model(
    entry: ModelEntry,
    settings: Settings,
    *,
    complete: Complete | None = None,
    evaluate_team: EvaluateTeam | None = None,
    now: datetime | None = None,
) -> tuple[EvaluationEvidence, bool]:
    """(signed evidence, passed). Evidence is returned even when checks failed so the
    caller can report them; only a passing result verifies later."""
    check_ready(entry, settings)
    if evaluate_team is None:
        from engine.evaluation import evaluate_team as real_evaluate_team

        evaluate_team = real_evaluate_team
    probe_results = await run_probes(complete or router_complete(entry))
    probes = [ProbeEvidence(name=p.name, passed=p.passed, detail=p.detail) for p in probe_results]
    with (
        pinned_for_evaluation(settings, entry),
        tempfile.TemporaryDirectory(prefix="asep-model-eval-") as tmp,
    ):
        scores = await evaluate_team(Path(tmp))
    tasks = task_evidence(scores)
    evidence = build_evidence(entry, tasks, probes, settings, now=now)
    passed = all(p.passed for p in probes) and all(t.passed for t in tasks)
    return evidence, passed
