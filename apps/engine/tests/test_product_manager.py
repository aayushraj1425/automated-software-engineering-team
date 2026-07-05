"""The Product Manager's plan contract: parsing and strict validation."""

import pytest

from engine.agents.product_manager import PlanError, parse_plan, validate_plan


def _plan(**overrides) -> dict:
    plan = {
        "summary": "Add a /status endpoint returning build info.",
        "tasks": [
            {
                "title": "Add the endpoint",
                "role": "backend",
                "description": "New route in the API app.",
                "depends_on": [],
            },
            {
                "title": "Show the status in the header",
                "role": "frontend",
                "description": "Poll the endpoint from the layout.",
                "depends_on": [1],
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_valid_plan_is_normalized():
    plan = validate_plan(_plan(summary="  padded summary  "))
    assert plan["summary"] == "padded summary"
    assert [t["role"] for t in plan["tasks"]] == ["backend", "frontend"]
    assert plan["tasks"][1]["depends_on"] == [1]


def test_plan_parsed_from_fenced_json():
    reply = '```json\n{"summary": "s", "tasks": []}\n```'
    assert parse_plan(reply) == {"summary": "s", "tasks": []}


def test_non_json_reply_is_rejected():
    with pytest.raises(PlanError, match="not valid JSON"):
        parse_plan("I think we should refactor everything.")


def test_missing_summary_is_rejected():
    with pytest.raises(PlanError, match="summary"):
        validate_plan(_plan(summary=""))


def test_unknown_role_is_rejected():
    bad = _plan()
    bad["tasks"][0]["role"] = "architect"
    with pytest.raises(PlanError, match="role"):
        validate_plan(bad)


def test_forward_dependency_is_rejected():
    bad = _plan()
    bad["tasks"][0]["depends_on"] = [2]  # a task cannot depend on a later one
    with pytest.raises(PlanError, match="earlier tasks"):
        validate_plan(bad)


def test_empty_task_list_is_rejected():
    with pytest.raises(PlanError, match="tasks"):
        validate_plan(_plan(tasks=[]))
