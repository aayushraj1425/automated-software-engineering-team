#!/usr/bin/env python
"""Trigger ONE real agent run from the terminal and let the engine open a PR.

Run from the repo root (the dev stack must be up: `pnpm db:up`):

    uv run --project apps/engine python run_agent_demo.py
    uv run --project apps/engine python run_agent_demo.py --repo https://github.com/you/repo --request "Add X"

It creates a run, auto-approves the plan, executes it, and prints the PR URL.
This is the same pipeline the /runs page drives — it just starts it from the
terminal instead of the browser.

Needs GEMINI_API_KEY (or your MODEL_* provider key) and a write-capable
GITHUB_TOKEN in the root .env. NOTE: this makes real model calls (small cost)
and opens a real pull request on the target repo each time you run it.
"""

import argparse
import asyncio
import os
import sys
from decimal import Decimal

# --- Bootstrap --------------------------------------------------------------
# The `engine` package and all its dependencies live in the uv-managed
# virtualenv under apps/engine, NOT in your system Python. So a bare
# `python run_agent_demo.py` can't import them. If that is how we were
# launched, re-run ourselves under uv so it just works from the repo root.
if os.environ.get("_RUN_AGENT_BOOTSTRAPPED") != "1":
    try:
        import engine  # noqa: F401  (probe: are we inside the engine venv?)
    except ModuleNotFoundError:
        import shutil
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parent
        uv = shutil.which("uv")
        if uv is None:
            candidate = Path.home() / ".local" / "bin" / "uv.exe"
            uv = str(candidate) if candidate.exists() else None
        if uv is None:
            raise SystemExit(
                "Cannot import 'engine', and 'uv' is not on PATH.\n"
                "Run it explicitly:\n"
                "  uv run --project apps/engine python run_agent_demo.py"
            )
        raise SystemExit(
            subprocess.call(
                [uv, "run", "--project", str(root / "apps" / "engine"),
                 "python", str(Path(__file__).resolve()), *sys.argv[1:]],
                env={**os.environ, "_RUN_AGENT_BOOTSTRAPPED": "1"},
            )
        )
# ----------------------------------------------------------------------------

if sys.platform == "win32":
    # psycopg's async driver needs the selector loop on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from engine.config import get_settings  # noqa: E402

# A terminal run has no logged-in user, so there is no per-user provider key in
# the database; bridge the .env key into os.environ for litellm's fallback.
_key = get_settings().gemini_api_key
if _key:
    os.environ.setdefault("GEMINI_API_KEY", _key)

from engine.agents.runner import execute_tasks, plan_run  # noqa: E402
from engine.db.enums import RunStatus  # noqa: E402
from engine.db.models import AgentEvent, AgentRun, Repository  # noqa: E402
from engine.db.session import session_scope  # noqa: E402

DEFAULT_REPO = "https://github.com/aayushraj1425/Test_ASEP"
DEFAULT_REQUEST = (
    "Add a greeting module in greeting.py with a function greet(name) that "
    "returns 'Hello, <name>!' and raises ValueError on an empty name. "
    "Add pytest tests in test_greeting.py covering both cases."
)


async def run(repo_url: str, request: str, max_cost: Decimal) -> None:
    settings = get_settings()
    print(
        f"[config] llm_fake={settings.llm_fake} coder={settings.model_coder} "
        f"github_token={'set' if settings.github_token else 'MISSING'}",
        flush=True,
    )

    async with session_scope() as session:
        repo = Repository(owner_id="manual-run", url=repo_url)
        session.add(repo)
        await session.flush()
        agent_run = AgentRun(
            user_id="manual-run",
            repository_id=repo.id,
            request=request,
            status=RunStatus.QUEUED,
            max_cost_usd=max_cost,
        )
        session.add(agent_run)
        await session.commit()
        run_id = agent_run.id
    print(f"[run] id={run_id}", flush=True)

    print("=== PLANNING ===", flush=True)
    await plan_run(run_id)
    async with session_scope() as session:
        agent_run = await session.get(AgentRun, run_id)
        assert agent_run is not None
        print(f"[plan] status={agent_run.status}", flush=True)
        if agent_run.status != RunStatus.AWAITING_APPROVAL:
            print(f"[plan] did NOT reach approval: {agent_run.error}", flush=True)
            return
        # Auto-approve (the "Approve" click on the /runs page).
        agent_run.status = RunStatus.EXECUTING
        session.add(AgentEvent(run_id=run_id, type="plan.approved", payload={"by": "manual-run"}))
        await session.commit()

    print("=== EXECUTING (code -> review -> sandbox -> scans -> open PR) ===", flush=True)
    await execute_tasks(run_id)
    async with session_scope() as session:
        agent_run = await session.get(AgentRun, run_id)
        assert agent_run is not None
        print("=== RESULT ===", flush=True)
        print(f"[result] status={agent_run.status}", flush=True)
        print(f"[result] error={agent_run.error}", flush=True)
        print(f"[result] cost_usd={agent_run.total_cost_usd}", flush=True)
        print(f"[result] pr_url={agent_run.pr_url}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger one real agent run and open a PR.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Git repo URL to run against")
    parser.add_argument("--request", default=DEFAULT_REQUEST, help="The feature to build")
    parser.add_argument(
        "--max-cost", type=Decimal, default=Decimal("2.00"), help="Spend cap in USD"
    )
    args = parser.parse_args()
    asyncio.run(run(args.repo, args.request, args.max_cost))


if __name__ == "__main__":
    main()
