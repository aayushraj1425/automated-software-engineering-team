"""The Quick team templates: shape, safety of the report-only team, and independence."""

import dataclasses

import pytest

from engine.agents.quick_team import quick_template
from engine.agents.registry import get_agent_spec
from engine.agents.teams_types import Complexity, StageName
from engine.agents.triage import template_for
from engine.db.enums import AgentRole


def test_editing_template_runs_every_gate_before_publish():
    template = quick_template()
    assert template.name == "quick"
    assert template.complexity == Complexity.QUICK
    assert template.stages == (
        StageName.PLAN,
        StageName.BUILD,
        StageName.SANDBOX,
        StageName.SECURITY,
        StageName.DEPENDENCY,
        StageName.PUBLISH,
    )
    assert [seat.key for seat in template.seats] == ["backend:engineer"]


def test_report_template_is_read_only_and_cannot_publish():
    template = quick_template(test_only=True)
    assert template.name == "test_report"
    assert template.complexity == Complexity.QUICK
    assert template.stages == (StageName.PLAN, StageName.TEST_REPORT)
    assert [seat.key for seat in template.seats] == ["qa:engineer"]
    # Nothing edits or ships on this team, so none of those stages may appear.
    assert not {StageName.BUILD, StageName.PUBLISH, StageName.PREVIEW_DEPLOY} & set(template.stages)


@pytest.mark.parametrize("test_only", [False, True])
def test_seat_keys_match_role_and_level(test_only):
    for seat in quick_template(test_only).seats:
        assert seat.key == f"{seat.role.value}:{seat.level.value}"
        assert seat.model is None  # roster assembly chooses models, not the template
        assert seat.reason


@pytest.mark.parametrize("test_only", [False, True])
def test_seat_levels_agree_with_the_registry(test_only):
    for seat in quick_template(test_only).seats:
        assert seat.level == get_agent_spec(seat.role).seat_level


def test_template_names_match_the_triage_mapping():
    assert quick_template().name == template_for(Complexity.QUICK, False)
    assert quick_template(True).name == template_for(Complexity.QUICK, True)
    assert quick_template(True).name == template_for(Complexity.COMPLEX, True)


def test_editing_team_has_one_seat_for_the_quick_board_role():
    # Quick boards are at most two tasks for one engineer (the backend role).
    assert {s.role for s in quick_template().seats} == {AgentRole.BACKEND}


def test_each_call_returns_independent_objects():
    first, second = quick_template(), quick_template()
    first.seats[0].model = "anthropic/claude-sonnet-5-5"
    assert second.seats[0].model is None
    assert first is not second and first.seats[0] is not second.seats[0]


def test_template_is_immutable():
    template = quick_template()
    with pytest.raises(dataclasses.FrozenInstanceError):
        template.name = "other"  # type: ignore[misc]
