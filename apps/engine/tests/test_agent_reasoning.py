"""Agent reasoning on the timeline: a tool-calling turn's text is surfaced.

The offline pipeline never triggers this (the fake model returns no tool calls),
so the loop's emission is proven directly with a stubbed model that returns a
reasoning-plus-tool turn. Design note: docs/architecture/AGENT_REASONING_TIMELINE.md.
"""

import uuid

from engine.agents.loop import LlmUsage, run_tool_loop
from engine.agents.registry import get_agent_spec
from engine.db.enums import AgentRole
from engine.llm import router as router_mod
from engine.llm.router import AssistantTurn, ToolCall
from engine.workspace.manager import Workspace


def _ws(tmp_path) -> Workspace:
    return Workspace(run_id=uuid.uuid4(), path=tmp_path, branch="b", base_sha="")


def _stub_turns(monkeypatch, turns: list[AssistantTurn]) -> None:
    it = iter(turns)

    async def fake_complete(tier, messages, tools):
        return next(it)

    monkeypatch.setattr(router_mod.model_router, "complete_with_tools", fake_complete)


async def test_reasoning_turn_emits_final_turn_does_not(tmp_path, monkeypatch):
    spec = get_agent_spec(AgentRole.BACKEND)
    _stub_turns(
        monkeypatch,
        [
            AssistantTurn(
                content="I'll list the directory first to see the layout.",
                tool_calls=(ToolCall(id="c1", name="list_dir", arguments={"path": "."}),),
                message={"role": "assistant", "content": "reasoning + call"},
            ),
            AssistantTurn(
                content="Done — nothing to change.",
                tool_calls=(),
                message={"role": "assistant", "content": "Done — nothing to change."},
            ),
        ],
    )

    reasoning: list[str] = []
    tools: list[str] = []

    async def on_reasoning(text: str) -> None:
        reasoning.append(text)

    async def on_tool(name, args, result) -> None:
        tools.append(name)

    result = await run_tool_loop(
        spec, _ws(tmp_path), [{"role": "user", "content": "x"}], LlmUsage(), on_tool, on_reasoning
    )

    assert result == "Done — nothing to change."
    # Only the tool-calling turn's text is reasoning; the final answer is not.
    assert reasoning == ["I'll list the directory first to see the layout."]
    assert tools == ["list_dir"]


async def test_tool_turn_without_text_emits_no_reasoning(tmp_path, monkeypatch):
    spec = get_agent_spec(AgentRole.BACKEND)
    _stub_turns(
        monkeypatch,
        [
            AssistantTurn(
                content="   ",  # whitespace only → not reasoning
                tool_calls=(ToolCall(id="c1", name="list_dir", arguments={"path": "."}),),
                message={"role": "assistant", "content": ""},
            ),
            AssistantTurn(
                content="done", tool_calls=(), message={"role": "assistant", "content": "done"}
            ),
        ],
    )

    reasoning: list[str] = []

    async def on_reasoning(text: str) -> None:
        reasoning.append(text)

    await run_tool_loop(
        spec, _ws(tmp_path), [{"role": "user", "content": "x"}], LlmUsage(), None, on_reasoning
    )

    assert reasoning == []
