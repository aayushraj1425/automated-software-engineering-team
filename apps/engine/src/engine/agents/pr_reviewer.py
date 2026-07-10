"""Reviews a pull request's unified diff and returns findings.

Unlike the run Reviewer (engine/agents/reviewer.py), which reads a live
workspace with tools, this one is given only the diff text — it is what the
webhook reviewer has for someone else's pull request. One planner-tier model
call returns a strict JSON verdict; the result is rendered as a markdown review
comment. With LLM_FAKE=1 a canned review is returned so the path is testable
offline. Design note: docs/architecture/WEBHOOK_REVIEWER.md.
"""

from typing import Any

from engine.agents.loop import parse_json_object
from engine.config import get_settings
from engine.llm.router import model_router

# The diff sent to the model is bounded so a huge pull request cannot blow up
# the prompt; the tail is dropped with a marker.
_MAX_DIFF_CHARS = 60_000

_SEVERITIES = ("high", "medium", "low")

REVIEW_FORMAT = """Reply with only a JSON object, nothing around it:
{
  "summary": "<one-paragraph overall assessment>",
  "findings": [
    {
      "path": "<file path from the diff>",
      "line": <line number in the new file, or null>,
      "severity": "high" | "medium" | "low",
      "issue": "<what is wrong and what to change>"
    }
  ]
}
Report only findings that matter: correctness bugs, security issues, broken
contracts, missing tests. No style nitpicks. An all-clear review has an empty
findings list."""

SYSTEM_PROMPT = (
    "You are the Reviewer on an AI software engineering team, reviewing a pull "
    "request someone opened on GitHub. You see only the unified diff. Judge the "
    "change for correctness, security, broken contracts, and missing tests, in "
    "that order. Be concrete: cite the file and line and say what to change."
)


class PrReviewError(Exception):
    """The model's review was missing or malformed after a retry."""


async def review_diff(diff: str) -> dict[str, Any]:
    """Return a validated review: {"summary": str, "findings": [...]}."""
    if get_settings().llm_fake:
        return {"summary": "Automated review (offline): no blocking issues found.", "findings": []}

    if not diff.strip():
        return {"summary": "The pull request has an empty diff; nothing to review.", "findings": []}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (f"Review this pull request diff:\n\n{_clamp(diff)}\n\n{REVIEW_FORMAT}"),
        },
    ]
    reply = await model_router.complete("planner", messages)
    try:
        return _validate(parse_json_object(reply))
    except (ValueError, PrReviewError):
        # One corrective round: restate the contract and try again.
        messages.append(
            {"role": "user", "content": f"That reply was not accepted.\n\n{REVIEW_FORMAT}"}
        )
        reply = await model_router.complete("planner", messages)
        return _validate(parse_json_object(reply))


def _clamp(diff: str) -> str:
    if len(diff) <= _MAX_DIFF_CHARS:
        return diff
    return diff[:_MAX_DIFF_CHARS] + "\n\n[diff truncated — too large to review in full]"


def _validate(review: dict[str, Any]) -> dict[str, Any]:
    summary = review.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise PrReviewError("review needs a non-empty summary")
    raw_findings = review.get("findings") or []
    if not isinstance(raw_findings, list):
        raise PrReviewError("findings must be a list")

    findings: list[dict[str, Any]] = []
    for number, item in enumerate(raw_findings, start=1):
        if not isinstance(item, dict):
            raise PrReviewError(f"finding {number} must be an object")
        issue = item.get("issue")
        if not isinstance(issue, str) or not issue.strip():
            raise PrReviewError(f"finding {number} needs an issue description")
        severity = item.get("severity")
        if severity not in _SEVERITIES:
            severity = "medium"  # tolerate a missing/odd severity rather than reject the review
        line = item.get("line")
        findings.append(
            {
                "path": str(item.get("path") or "").strip(),
                "line": line if isinstance(line, int) else None,
                "severity": severity,
                "issue": issue.strip(),
            }
        )
    return {"summary": summary.strip(), "findings": findings}


def render_review_comment(review: dict[str, Any]) -> str:
    """Render a validated review as the markdown body of a PR review comment."""
    lines = ["## 🤖 ASEP automated review", "", review["summary"], ""]
    findings = review["findings"]
    if not findings:
        lines.append("No blocking issues found.")
    else:
        # Most severe first so the important findings are read first.
        order = {sev: rank for rank, sev in enumerate(_SEVERITIES)}
        lines.append(f"### Findings ({len(findings)})")
        for f in sorted(findings, key=lambda f: order.get(f["severity"], len(_SEVERITIES))):
            where = f["path"] or "(unknown file)"
            if f["line"] is not None:
                where += f":{f['line']}"
            lines.append(f"- **[{f['severity']}]** `{where}` — {f['issue']}")
    lines += ["", "_Posted automatically by the ASEP reviewer._"]
    return "\n".join(lines)
