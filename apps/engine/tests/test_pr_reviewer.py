"""The diff-based PR reviewer: contract validation and comment rendering.

The model is not called here — LLM_FAKE (set in conftest) short-circuits
review_diff to a canned all-clear, and the validation/rendering helpers are
pure. Design note: docs/architecture/WEBHOOK_REVIEWER.md.
"""

import pytest

from engine.agents.pr_reviewer import (
    PrReviewError,
    _validate,
    render_review_comment,
    review_diff,
)
from engine.config import get_settings


async def test_offline_review_is_all_clear():
    review = await review_diff("diff --git a/x b/x\n+print('hi')\n")
    assert review["findings"] == []
    assert review["summary"]


async def test_empty_diff_is_not_reviewed(monkeypatch):
    # Even with a model configured, an empty diff never reaches it.
    monkeypatch.setattr(get_settings(), "llm_fake", False)
    review = await review_diff("   \n  ")
    assert review["findings"] == []
    assert "empty diff" in review["summary"]


def test_validate_keeps_good_findings():
    raw = {
        "summary": "One real bug.",
        "findings": [
            {"path": "app.py", "line": 12, "severity": "high", "issue": "null deref"},
        ],
    }
    clean = _validate(raw)
    assert clean["findings"][0]["line"] == 12
    assert clean["findings"][0]["severity"] == "high"


def test_validate_tolerates_a_bad_severity():
    raw = {"summary": "s", "findings": [{"issue": "x", "severity": "critical"}]}
    clean = _validate(raw)
    assert clean["findings"][0]["severity"] == "medium"  # coerced, not rejected
    assert clean["findings"][0]["line"] is None  # missing line becomes None


def test_validate_rejects_a_missing_summary():
    with pytest.raises(PrReviewError):
        _validate({"summary": "  ", "findings": []})


def test_validate_rejects_a_finding_without_an_issue():
    with pytest.raises(PrReviewError):
        _validate({"summary": "s", "findings": [{"path": "a.py"}]})


def test_render_orders_findings_by_severity():
    review = {
        "summary": "Mixed.",
        "findings": [
            {"path": "b.py", "line": 3, "severity": "low", "issue": "nit"},
            {"path": "a.py", "line": 9, "severity": "high", "issue": "crash"},
        ],
    }
    body = render_review_comment(review)
    assert body.index("[high]") < body.index("[low]")  # high listed first
    assert "`a.py:9`" in body


def test_render_all_clear_review():
    body = render_review_comment({"summary": "Looks good.", "findings": []})
    assert "No blocking issues found." in body
