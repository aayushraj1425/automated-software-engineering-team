"""Evaluate one catalog model and, if it passes everything, write signed evidence.

Usage, inside apps/engine (Postgres must be running for the golden tasks):

    uv run python scripts/eval_open_model.py openai_compatible/qwen3-coder:30b
    uv run python scripts/eval_open_model.py <model id> --probes-only

The model must be in MODEL_CATALOG (with its base_url for open source endpoints).
Runs the tool call probes, then the three golden tasks from docs/EVALUATION.md with
every seat pinned to the model. Only a run where everything passes writes the
results file that lets the model join auto selection. Needs real model access:
LLM_FAKE=1 is refused. Exit code 0 means the model passed and evidence was saved.
"""

import argparse
import asyncio
import sys

# psycopg async cannot run on Windows' default ProactorEventLoop, and the
# cp1252 console cannot print model output — force UTF-8.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from engine.config import get_settings  # noqa: E402
from engine.llm.catalog import ModelSelectionError  # noqa: E402
from engine.llm.evaluate import check_ready, evaluate_model, router_complete  # noqa: E402
from engine.llm.evidence import save_evidence  # noqa: E402
from engine.llm.probes import run_probes  # noqa: E402


async def main(model_id: str, probes_only: bool) -> int:
    settings = get_settings()
    entry = next((m for m in settings.model_catalog if m.id == model_id), None)
    if entry is None:
        print(f"{model_id} is not in MODEL_CATALOG")
        return 2
    try:
        check_ready(entry, settings)
    except ModelSelectionError as error:
        print(f"Cannot evaluate: {error}")
        return 2
    print(f"Evaluating {entry.id}\n")

    if probes_only:
        for probe in await run_probes(router_complete(entry)):
            print(f"  [{'PASS' if probe.passed else 'FAIL'}] {probe.name}: {probe.detail}")
        print("\nProbes only: nothing was saved and the model is not certified.")
        return 0

    evidence, passed = await evaluate_model(entry, settings)
    for probe in evidence.probes:
        print(f"  [{'PASS' if probe.passed else 'FAIL'}] tool call: {probe.name}  {probe.detail}")
    for task in evidence.tasks:
        verdict = "PASS" if task.passed else "FAIL"
        print(f"  [{verdict}] golden task: {task.name}  cost ${task.cost_usd:.4f}")
        if task.error:
            print(f"         reason: {task.error}")
    if not passed:
        print("\nNot certified: nothing was saved.")
        return 1
    path = save_evidence(evidence, settings)
    print(f"\nPassed. Signed results saved to {path}")
    print("Auto selection also needs the organization switch (PUT /v1/model-policy).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("model_id")
    parser.add_argument("--probes-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.model_id, args.probes_only)))
