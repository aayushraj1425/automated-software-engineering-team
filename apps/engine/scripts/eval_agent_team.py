"""Run the agent team against the three golden tasks and print the scorecard.

Usage, inside apps/engine (Postgres must be running — `pnpm db:up`):

    uv run python scripts/eval_agent_team.py

With LLM_FAKE=1 only the pipeline mechanics are scored; with a real model
the diff content is judged too. Exit code 0 means every task passed.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# psycopg async cannot run on Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from engine.config import get_settings  # noqa: E402
from engine.evaluation import evaluate_team  # noqa: E402


async def main() -> int:
    mode = "offline (LLM_FAKE=1)" if get_settings().llm_fake else "real model"
    print(f"Golden-task evaluation — {mode}\n")

    with tempfile.TemporaryDirectory(prefix="asep-eval-") as tmp:
        scores = await evaluate_team(Path(tmp))

    for score in scores:
        verdict = "PASS" if score.passed else "FAIL"
        diff = "n/a" if score.diff_matched is None else ("yes" if score.diff_matched else "NO")
        print(
            f"  [{verdict}] {score.name}\n"
            f"         planned {'yes' if score.planned else 'NO'} · "
            f"completed {'yes' if score.completed else 'NO'} · "
            f"commits {'yes' if score.committed else 'NO'} · diff match {diff}"
        )
        if score.error:
            print(f"         reason: {score.error}")

    passed = sum(score.passed for score in scores)
    print(f"\n{passed}/{len(scores)} golden tasks passed")
    return 0 if passed == len(scores) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
