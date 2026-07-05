"""Reviewer agent: reads the run's diff and returns a verdict.

The Reviewer is read-only — it inspects the diff and the touched files, then
answers with a strictly validated JSON verdict. Findings are tagged with the
engineer role that should fix them; the runner grants one revision round and
the second verdict is final. With LLM_FAKE=1 the verdict is approve, so the
offline pipeline completes deterministically.
"""

from typing import Any

from engine.agents.loop import LlmUsage, parse_json_object, run_tool_loop
from engine.agents.product_manager import ENGINEER_ROLES
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.workspace.manager import Workspace

APPROVE = "approve"
REQUEST_CHANGES = "request_changes"

VERDICT_FORMAT = """Reply with only a JSON object, nothing around it:
{
  "verdict": "approve" | "request_changes",
  "findings": [
    {
      "role": "backend" | "frontend" | "devops",
      "issue": "<file and location, what is wrong, and what to change>"
    }
  ]
}
An approve verdict has an empty findings list."""


class ReviewError(Exception):
    """The model's verdict was missing or malformed; the message says why."""


async def review_run(
    request: str, plan_summary: str, ws: Workspace, usage: LlmUsage
) -> dict[str, Any]:
    if get_settings().llm_fake:
        return {"verdict": APPROVE, "findings": []}

    spec = get_agent_spec(AgentRole.REVIEWER)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Feature request:\n{request}\n\n"
                f"Approved plan summary:\n{plan_summary}\n\n"
                "Review the engineers' work: start with git_diff, then read the "
                f"touched files in full.\n\n{VERDICT_FORMAT}"
            ),
        },
    ]
    reply = await run_tool_loop(spec, ws, messages, usage)
    try:
        return validate_verdict(parse_verdict(reply))
    except ReviewError as exc:
        # One corrective round: show the model its mistake and ask again.
        messages.append(
            {"role": "user", "content": f"That verdict was rejected: {exc}\n\n{VERDICT_FORMAT}"}
        )
        reply = await run_tool_loop(spec, ws, messages, usage)
        return validate_verdict(parse_verdict(reply))


def parse_verdict(reply: str) -> dict[str, Any]:
    try:
        return parse_json_object(reply)
    except ValueError as exc:
        raise ReviewError(f"verdict {exc}") from exc


def validate_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    decision = verdict.get("verdict")
    findings = verdict.get("findings") or []
    if decision not in (APPROVE, REQUEST_CHANGES):
        raise ReviewError(f"verdict must be {APPROVE!r} or {REQUEST_CHANGES!r}, got {decision!r}")
    if not isinstance(findings, list):
        raise ReviewError("findings must be a list")
    if decision == REQUEST_CHANGES and not findings:
        raise ReviewError("request_changes needs at least one finding")

    clean_findings: list[dict[str, str]] = []
    for number, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            raise ReviewError(f"finding {number} must be an object")
        issue = finding.get("issue")
        if not isinstance(issue, str) or not issue.strip():
            raise ReviewError(f"finding {number} needs an issue description")
        role = finding.get("role")
        if role not in ENGINEER_ROLES:
            raise ReviewError(
                f"finding {number} has role {role!r}; allowed roles: {sorted(ENGINEER_ROLES)}"
            )
        clean_findings.append({"role": role, "issue": issue.strip()})
    return {"verdict": decision, "findings": clean_findings}
