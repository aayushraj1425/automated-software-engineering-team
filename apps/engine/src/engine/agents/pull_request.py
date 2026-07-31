"""Build the body of a run's pull/merge request.

A pure function over the plan summary and the run id: the plan the team wrote,
plus the project's Definition-of-Done checklist for the human reviewer. It is
host-agnostic — GitHub, GitLab, and Bitbucket all open their request with the
same body — and touches no model, database, or network, so it is trivially
testable and works offline (the same shape as `engine.reporting`).

The checklist mirrors `.github/PULL_REQUEST_TEMPLATE.md`. It is embedded here
rather than read from disk because the deployed engine ships without the
repository's `.github/` directory; a test pins the two in sync. The boxes are
left unchecked — the agent team cannot honestly self-certify a human review, so
completing the checklist is the reviewer's job.

Design note: docs/architecture/PULL_REQUEST_BODY.md.
"""

import uuid

# The Definition-of-Done items, verbatim from .github/PULL_REQUEST_TEMPLATE.md.
# Kept in sync by tests/test_pull_request_body.py.
DEFINITION_OF_DONE: tuple[str, ...] = (
    "Architecture note / ADR updated (or N/A — say why)",
    "API specification updated (OpenAPI regenerated → `packages/shared`) (or N/A)",
    "Database schema migration included (or N/A)",
    "UI/UX reviewed against the design intent (or N/A)",
    "Implementation complete — no TODOs left without backlog items",
    "Unit tests added/updated",
    "Integration tests added/updated (or N/A — say why)",
    "Documentation updated (README / docs/ / CLAUDE.md)",
    "Performance considered (hot paths, N+1 queries, payload sizes, token spend)",
    "Security reviewed (input validation, authz, secrets handling, ADR-0008 tool jail)",
)


def build_pull_request_body(plan_summary: str, run_id: uuid.UUID) -> str:
    """The markdown body for the run's pull/merge request: a Summary section (the
    plan), an attribution line, and the Definition-of-Done checklist for the
    reviewer to verify."""
    checklist = "\n".join(f"- [ ] {item}" for item in DEFINITION_OF_DONE)
    return (
        "## Summary\n\n"
        f"{plan_summary.strip() or '_No plan summary was produced._'}\n\n"
        f"_Opened by the ASEP agent team (run {run_id})._\n\n"
        "## Definition of Done\n\n"
        "These boxes are the reviewer's to verify — the agent team cannot "
        "self-certify a human review.\n\n"
        f"{checklist}\n"
    )
