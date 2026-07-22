"""The run report: a shareable markdown summary built from the run record.

Pure function, no DB — the objects are constructed in memory. Design note:
docs/architecture/RUN_REPORT.md.
"""

import uuid
from decimal import Decimal

from engine.db.models import AgentRun, AgentTask
from engine.reporting import build_run_report


def test_report_covers_request_plan_tasks_and_outcome():
    run = AgentRun(
        id=uuid.uuid4(),
        user_id="u",
        request="Add a /stats endpoint\n\nreturning the item count",
        status="completed",
        pr_url="https://git.example/pr/1",
        total_cost_usd=Decimal("0.1234"),
        total_input_tokens=100,
        total_output_tokens=50,
        plan={"summary": "Add a stats endpoint and a test."},
    )
    tasks = [
        AgentTask(
            run_id=run.id,
            sequence=1,
            role="backend",
            title="Add GET /stats",
            status="done",
            result="added the endpoint and a test",
            depends_on=[],
        ),
        AgentTask(
            run_id=run.id,
            sequence=2,
            role="frontend",
            title="Show the count",
            status="skipped",
            result=None,
            depends_on=[],
        ),
    ]

    md = build_run_report(run, tasks, "https://github.com/x/y")

    assert md.startswith("# Run report — Add a /stats endpoint")  # first line only
    assert "Add a stats endpoint and a test." in md  # plan summary
    assert "1. **Add GET /stats** — _backend_ · done" in md
    assert "   - added the endpoint and a test" in md
    assert "2. **Show the count** — _frontend_ · skipped" in md
    assert "**Pull request:** https://git.example/pr/1" in md
    assert "$0.1234" in md
    assert "1/2 completed" in md


def test_report_is_defensive_about_an_unplanned_failed_run():
    run = AgentRun(
        id=uuid.uuid4(),
        user_id="u",
        request="Do a thing",
        status="failed",
        error="planning crashed",
    )

    md = build_run_report(run, [], None)

    assert "**Status:** failed" in md
    assert "**Failed:** planning crashed" in md
    assert "0/0 completed" in md
    assert "not connected" in md
    assert "$0.0000" in md  # unset cost reads as zero, not a crash
    assert "## Tasks" not in md  # nothing to list
