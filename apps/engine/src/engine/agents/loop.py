"""The shared agent loop: ask the model, run its tool calls, repeat.

Every role uses the same loop; only the system prompt, model tier, and tool
allow-list differ (all three come from the registry). The loop ends when the
model replies without tool calls — that text is the agent's final answer.
"""

import json
from dataclasses import dataclass
from typing import Any

import structlog

from engine.agents.registry import AgentSpec
from engine.agents.tools import call_tool, schemas_for
from engine.llm.router import AssistantTurn, model_router
from engine.workspace.manager import Workspace

log = structlog.get_logger(__name__)

# An agent gets this many model turns per task before the attempt fails.
MAX_TURNS = 24


class AgentLoopError(Exception):
    """The agent could not finish within its turn budget."""


@dataclass
class LlmUsage:
    """Token and cost totals accumulated across one agent's model turns."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, turn: AssistantTurn) -> None:
        self.input_tokens += turn.input_tokens
        self.output_tokens += turn.output_tokens
        self.cost_usd += turn.cost_usd


def parse_json_object(reply: str) -> dict[str, Any]:
    """An agent's final answer as a JSON object; tolerates a markdown fence.
    Raises ValueError with a readable reason — callers wrap it in their
    contract-specific error."""
    text = reply.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("reply must be a JSON object")
    return data


async def run_tool_loop(
    spec: AgentSpec, ws: Workspace, messages: list[dict[str, Any]], usage: LlmUsage
) -> str:
    tools = schemas_for(spec.tools)
    for _ in range(MAX_TURNS):
        turn = await model_router.complete_with_tools(spec.model_tier, messages, tools)
        usage.add(turn)
        messages.append(turn.message)
        if not turn.tool_calls:
            return turn.content or ""
        for call in turn.tool_calls:
            result = await call_tool(ws, spec.tools, call.name, call.arguments)
            log.info("agent.tool_call", role=spec.role, tool=call.name)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise AgentLoopError(f"{spec.role} did not finish within {MAX_TURNS} model turns")
