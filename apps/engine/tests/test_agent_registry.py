"""The registry is the contract between roles, prompts, tools, and model tiers."""

import pytest

from engine.agents.registry import all_agent_specs, get_agent_spec
from engine.db.enums import AgentRole

VALID_TIERS = {"planner", "coder", "cheap"}
WRITE_TOOLS = {"apply_patch", "write_file", "git_commit", "git_branch"}


def test_every_role_has_a_spec():
    assert {spec.role for spec in all_agent_specs()} == set(AgentRole)


def test_specs_resolve_by_enum_and_by_string():
    assert get_agent_spec(AgentRole.BACKEND) is get_agent_spec("backend")
    with pytest.raises(ValueError):
        get_agent_spec("intern")


def test_model_tiers_are_router_tiers():
    for spec in all_agent_specs():
        assert spec.model_tier in VALID_TIERS, spec.role


def test_every_prompt_file_exists_and_is_substantial():
    for spec in all_agent_specs():
        prompt = spec.system_prompt
        assert len(prompt) > 200, f"{spec.role} prompt looks like a stub"
        assert prompt.lstrip().startswith("You are"), spec.role


def test_read_only_roles_cannot_write():
    for role in (AgentRole.REVIEWER, AgentRole.PRODUCT_MANAGER, AgentRole.SUPERVISOR):
        tools = set(get_agent_spec(role).tools)
        assert not tools & WRITE_TOOLS, f"{role} must not hold write-side tools (ADR-0008)"


def test_engineers_share_the_jailed_toolset():
    backend = get_agent_spec(AgentRole.BACKEND).tools
    for role in (AgentRole.FRONTEND, AgentRole.DEVOPS):
        assert get_agent_spec(role).tools == backend
    assert "open_pr" not in backend, "opening the PR belongs to the run pipeline, not engineers"
