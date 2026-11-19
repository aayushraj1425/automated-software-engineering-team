"""Accuracy gate for the triage rules on the labelled golden requests.

Offline and deterministic. Same data and checks as the runnable command:
    uv run python -m engine.agents.triage_eval
"""

import json

import pytest

from engine.agents import triage_eval
from engine.agents.teams_types import Complexity, TriageDecision
from engine.agents.triage_eval import GOLDEN_FILE, SPLITS, evaluate, load_cases

MIN_ACCURACY = 0.9


def test_golden_file_is_well_formed():
    raw = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    assert {item["split"] for item in raw} == set(SPLITS)
    requests = [(item["request"], tuple(item.get("paths", ()))) for item in raw]
    assert len(requests) == len(set(requests)), "duplicate golden request"
    allowed = {"request", "complexity", "split", "test_only", "paths", "ambiguous"}
    for item in raw:
        assert set(item) <= allowed, item
        Complexity(item["complexity"])
        # Report-only is always a Quick label.
        assert not item.get("test_only") or item["complexity"] == "quick"


def test_golden_set_is_representative():
    cases = load_cases()
    assert len(cases) >= 100
    by_class = {c: sum(case.complexity == c for case in cases) for c in Complexity}
    assert all(count >= 25 for count in by_class.values()), by_class
    assert sum(case.test_only for case in cases) >= 15
    assert sum(bool(case.paths) for case in cases) >= 10
    assert sum(case.ambiguous for case in cases) >= 5
    # Both splits stay big enough to mean something on their own.
    assert all(len(load_cases(split)) >= 40 for split in SPLITS)


@pytest.mark.parametrize("split", ["all", *SPLITS])
def test_rules_meet_the_accuracy_gate(split):
    report = evaluate(load_cases(split))
    detail = triage_eval.format_report(report)
    assert report.accuracy >= MIN_ACCURACY, detail
    assert not report.false_test_only, detail
    assert not report.under_triaged, detail
    assert not report.ambiguous_not_declined, detail
    assert report.passes(MIN_ACCURACY), detail


def test_every_class_is_recalled_on_each_split():
    for split in SPLITS:
        for complexity, (hit, total) in evaluate(load_cases(split)).recall().items():
            assert total and hit / total >= MIN_ACCURACY, (split, complexity, hit, total)


def test_harness_detects_a_bad_classifier():
    def always_quick(request, paths):
        return TriageDecision(Complexity.QUICK, "bad", True)

    report = evaluate(load_cases(), always_quick)
    assert report.accuracy < 0.5
    assert report.false_test_only and report.under_triaged
    assert not report.passes(MIN_ACCURACY)


def test_harness_scores_declined_cases_as_standard():
    report = evaluate(load_cases(), lambda request, paths: None)
    assert not any(r.decided for r in report.results)
    assert report.decline_rate == 1
    assert all(r.complexity == Complexity.STANDARD and not r.test_only for r in report.results)
    # Declining everything means the cheap model decides everything; the gate rejects that.
    assert not report.passes(MIN_ACCURACY)


def test_command_line_exit_codes(capsys):
    assert triage_eval.main(["--split", "holdout", "--min-accuracy", "0.9"]) == 0
    out = capsys.readouterr().out
    assert "accuracy:" in out and out.strip().endswith("PASS")
    assert triage_eval.main(["--min-accuracy", "1.01", "--quiet"]) == 1
    assert capsys.readouterr().out.strip().endswith("FAIL")
