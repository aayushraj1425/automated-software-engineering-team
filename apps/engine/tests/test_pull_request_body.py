"""The pull request body: the plan summary plus the full Definition-of-Done
checklist. Pure builder, no DB. Design note: docs/architecture/PULL_REQUEST_BODY.md.
"""

import re
import uuid
from pathlib import Path

from engine.agents.pull_request import DEFINITION_OF_DONE, build_pull_request_body

_TEMPLATE = Path(__file__).resolve().parents[3] / ".github" / "PULL_REQUEST_TEMPLATE.md"


def test_body_has_summary_and_full_checklist():
    run_id = uuid.uuid4()
    body = build_pull_request_body("Add a /stats endpoint and a test.", run_id)

    assert "## Summary" in body
    assert "Add a /stats endpoint and a test." in body
    assert str(run_id) in body
    assert "## Definition of Done" in body
    # Every DoD item is present as an unchecked box.
    for item in DEFINITION_OF_DONE:
        assert f"- [ ] {item}" in body
    # None are pre-checked — the reviewer owns them.
    assert "- [x]" not in body


def test_blank_plan_summary_is_handled():
    body = build_pull_request_body("   ", uuid.uuid4())
    assert "_No plan summary was produced._" in body
    assert "## Definition of Done" in body


def test_checklist_stays_in_sync_with_the_template():
    """The embedded checklist must match .github/PULL_REQUEST_TEMPLATE.md, so the
    human-facing template and the agent-generated body never drift apart."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    from_template = tuple(re.findall(r"^- \[ \] (.+)$", template, flags=re.MULTILINE))
    assert from_template == DEFINITION_OF_DONE
