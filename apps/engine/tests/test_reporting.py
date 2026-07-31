"""The run report: a shareable markdown summary built from the run record.

Pure function, no DB — the objects are constructed in memory. Design note:
docs/architecture/runs-ui/RUN_REPORT.md.
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


def test_report_includes_the_agents_decisions_when_present():
    run = AgentRun(id=uuid.uuid4(), user_id="u", request="Add a flag", status="completed")

    without = build_run_report(run, [], None)
    assert "## Decisions" not in without  # no reasoning → no section

    reasoning = [
        ("backend", "I'll add the flag to settings first, then read it.\nMore detail ignored."),
        ("reviewer", "The change looks correct and in scope."),
        (None, "   "),  # blank text is dropped
    ]
    md = build_run_report(run, [], None, reasoning)

    assert "## Decisions" in md
    assert (
        "- _backend_: I'll add the flag to settings first, then read it." in md
    )  # first line only
    assert "- _reviewer_: The change looks correct and in scope." in md
    assert "More detail ignored." not in md  # only the first line is kept


def test_report_caps_a_long_decision_log():
    run = AgentRun(id=uuid.uuid4(), user_id="u", request="Big run", status="completed")
    reasoning = [("backend", f"decision number {i}") for i in range(40)]

    md = build_run_report(run, [], None, reasoning)

    assert "- _backend_: decision number 0" in md
    assert "- _backend_: decision number 24" in md
    assert "- _backend_: decision number 25" not in md  # capped at 25
    assert "_… and 15 more_" in md


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
