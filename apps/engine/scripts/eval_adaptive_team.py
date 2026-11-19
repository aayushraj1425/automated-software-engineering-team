"""Evaluate all three team sizes; requires a migrated development/test database.

uv run python scripts/eval_adaptive_team.py --fake --output adaptive-scorecard.json
uv run python scripts/eval_adaptive_team.py --live --output adaptive-scorecard.json
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from engine.adaptive_evaluation import evaluate_adaptive_team  # noqa: E402
from engine.config import get_settings  # noqa: E402
from engine.db.session import dispose_engine  # noqa: E402
from engine.events.bus import dispose_bus  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fake", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    get_settings().llm_fake = args.fake
    try:
        with tempfile.TemporaryDirectory(prefix="asep-adaptive-eval-") as tmp:
            scores = await asyncio.wait_for(evaluate_adaptive_team(Path(tmp)), args.timeout_seconds)
        report = {
            "fake": args.fake,
            "preview_deployment_validated": False,
            "scores": [score.as_dict() for score in scores],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for score in scores:
            print(f"{'PASS' if score.passed else 'FAIL'}: {score.name}; cost ${score.cost_usd:.4f}")
            if score.error:
                print(f"  {score.error}")
        print(f"Scorecard: {args.output.resolve()}")
        print(
            "Cloud deployment is separately approved; "
            "this scorecard does not validate a live preview."
        )
        return 0 if all(score.passed for score in scores) else 1
    finally:
        await dispose_bus()
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
