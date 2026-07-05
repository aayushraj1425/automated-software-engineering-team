"""The Reviewer's verdict contract: parsing and strict validation."""

import pytest

from engine.agents.reviewer import ReviewError, parse_verdict, validate_verdict
from engine.github import parse_github_repo


def test_approve_verdict_is_accepted():
    verdict = validate_verdict({"verdict": "approve", "findings": []})
    assert verdict == {"verdict": "approve", "findings": []}


def test_findings_are_normalized():
    verdict = validate_verdict(
        {
            "verdict": "request_changes",
            "findings": [{"role": "backend", "issue": "  src/app.py:12 misses the error case  "}],
        }
    )
    assert verdict["findings"] == [
        {"role": "backend", "issue": "src/app.py:12 misses the error case"}
    ]


def test_verdict_parsed_from_fenced_json():
    reply = '```json\n{"verdict": "approve", "findings": []}\n```'
    assert parse_verdict(reply) == {"verdict": "approve", "findings": []}


def test_unknown_verdict_is_rejected():
    with pytest.raises(ReviewError, match="verdict must be"):
        validate_verdict({"verdict": "maybe", "findings": []})


def test_request_changes_without_findings_is_rejected():
    with pytest.raises(ReviewError, match="at least one finding"):
        validate_verdict({"verdict": "request_changes", "findings": []})


def test_finding_with_unknown_role_is_rejected():
    with pytest.raises(ReviewError, match="role"):
        validate_verdict(
            {"verdict": "request_changes", "findings": [{"role": "reviewer", "issue": "x"}]}
        )


def test_github_urls_are_parsed_and_local_paths_are_not():
    assert parse_github_repo("https://github.com/acme/demo") == ("acme", "demo")
    assert parse_github_repo("https://github.com/acme/demo.git") == ("acme", "demo")
    assert parse_github_repo("git@github.com:acme/demo.git") == ("acme", "demo")
    assert parse_github_repo("C:/tmp/fixture-repo") is None
    assert parse_github_repo("https://gitlab.com/acme/demo") is None
