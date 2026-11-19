"""The two Quick team shapes (docs/architecture/agents/TRIAGE_RULES_AND_QUICK_TEAM.md).

``quick`` is one engineer who plans and makes a small change, then the usual gates.
``test_report`` is one QA seat that runs the sandbox and writes a report; it edits and
publishes nothing, so it has no scan or publish stages. The Teams workstream looks these
up through ``get_team_template``; models are filled in later by roster assembly.
"""

from engine.agents.teams_types import Complexity, Level, Seat, StageName, TeamTemplate
from engine.db.enums import AgentRole

_EDITING_STAGES = (
    StageName.PLAN,
    StageName.BUILD,
    StageName.SANDBOX,
    StageName.SECURITY,
    StageName.DEPENDENCY,
    StageName.PUBLISH,
)
_REPORT_STAGES = (StageName.PLAN, StageName.TEST_REPORT)


def _seat(role: AgentRole, level: Level, reason: str) -> Seat:
    return Seat(key=f"{role.value}:{level.value}", role=role, level=level, reason=reason)


def quick_template(test_only: bool = False) -> TeamTemplate:
    """A fresh template each call, so a caller can set a seat's model without side effects."""
    if test_only:
        return TeamTemplate(
            name="test_report",
            complexity=Complexity.QUICK,
            seats=(
                _seat(
                    AgentRole.QA,
                    Level.ENGINEER,
                    "runs the repository's tests in the sandbox and reports; edits nothing",
                ),
            ),
            stages=_REPORT_STAGES,
        )
    return TeamTemplate(
        name="quick",
        complexity=Complexity.QUICK,
        seats=(
            _seat(
                AgentRole.BACKEND,
                Level.ENGINEER,
                "one engineer plans and makes the small change",
            ),
        ),
        stages=_EDITING_STAGES,
    )
