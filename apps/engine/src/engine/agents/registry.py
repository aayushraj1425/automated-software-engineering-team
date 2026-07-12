"""Agent registry: role → system prompt + tool policy + model tier.

Configuration-driven so adding or retuning a role never touches runtime code:
the table below is the single place a role's model tier and tool policy live,
and prompts are versioned markdown assets in engine/agents/prompts/.

Tool names are declarative for now; the Agent Tools workstream binds them to
implementations, and the executor must enforce that an agent may only invoke
tools in its policy (ADR-0008 — deny by default).
"""

from dataclasses import dataclass
from pathlib import Path

from engine.db.enums import AgentRole
from engine.llm.router import Tier

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Read-side tools are safe for every role that looks at the workspace;
# search_code queries the repository's semantic index (read-only by nature).
_READ_TOOLS = ("list_dir", "read_file", "search", "search_code")
# Write-side tools stay jailed to the per-run workspace (ADR-0008).
_WRITE_TOOLS = ("apply_patch", "write_file")
_GIT_TOOLS = ("git_branch", "git_commit", "git_diff")


@dataclass(frozen=True)
class AgentSpec:
    role: AgentRole
    model_tier: Tier
    tools: tuple[str, ...]
    prompt_file: str

    @property
    def system_prompt(self) -> str:
        return (PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8")


_ENGINEER_TOOLS = (*_READ_TOOLS, *_WRITE_TOOLS, *_GIT_TOOLS, "update_task_status")

_REGISTRY: dict[AgentRole, AgentSpec] = {
    spec.role: spec
    for spec in (
        AgentSpec(
            role=AgentRole.SUPERVISOR,
            model_tier="cheap",
            # The supervisor routes deterministically on the task board; its
            # only judgement calls (summaries, failure notes) are cheap.
            tools=("update_task_status",),
            prompt_file="supervisor.md",
        ),
        AgentSpec(
            role=AgentRole.PRODUCT_MANAGER,
            model_tier="planner",
            tools=(*_READ_TOOLS, "create_tasks"),
            prompt_file="product_manager.md",
        ),
        AgentSpec(
            role=AgentRole.BACKEND,
            model_tier="coder",
            tools=_ENGINEER_TOOLS,
            prompt_file="backend.md",
        ),
        AgentSpec(
            role=AgentRole.FRONTEND,
            model_tier="coder",
            tools=_ENGINEER_TOOLS,
            prompt_file="frontend.md",
        ),
        AgentSpec(
            role=AgentRole.DEVOPS,
            model_tier="coder",
            tools=_ENGINEER_TOOLS,
            prompt_file="devops.md",
        ),
        AgentSpec(
            role=AgentRole.REVIEWER,
            model_tier="planner",
            # Review is read-only by design: findings go back to the engineers,
            # the reviewer never edits the workspace itself.
            tools=(*_READ_TOOLS, "git_diff"),
            prompt_file="reviewer.md",
        ),
        AgentSpec(
            role=AgentRole.QA,
            model_tier="coder",
            # QA fixes failing tests, so it needs the full engineer tool set
            # (read, edit, commit) — minus task-board tools it never touches.
            tools=(*_READ_TOOLS, *_WRITE_TOOLS, *_GIT_TOOLS),
            prompt_file="qa.md",
        ),
        AgentSpec(
            role=AgentRole.SCRUM_MASTER,
            model_tier="planner",
            # Planning is read-only: the Scrum Master reads the repository index
            # for context and returns a roadmap; it never edits the workspace.
            tools=_READ_TOOLS,
            prompt_file="scrum_master.md",
        ),
        AgentSpec(
            role=AgentRole.TECHNICAL_WRITER,
            model_tier="planner",
            # Documentation is read-only: the Technical Writer reads the index
            # for context and returns prose; it never edits the workspace.
            tools=_READ_TOOLS,
            prompt_file="technical_writer.md",
        ),
    )
}


def get_agent_spec(role: AgentRole | str) -> AgentSpec:
    return _REGISTRY[AgentRole(role)]


def all_agent_specs() -> tuple[AgentSpec, ...]:
    return tuple(_REGISTRY.values())
