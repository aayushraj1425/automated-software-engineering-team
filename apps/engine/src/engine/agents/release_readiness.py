"""Release Engineer: a short readiness note shown to the human before a deploy approval.

The seat is read-only and never sees cloud credentials; this module is given only
the preview options (chart path, smoke paths, lifetime). The note is advice for the
approver, not a gate: the approval itself stays a human decision.
"""

from typing import Any

from engine.agents.loop import LlmUsage, ReasoningObserver, ToolObserver, run_tool_loop
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.deploy.contracts import PreviewOptions
from engine.workspace.manager import Workspace

MAX_NOTE_CHARS = 4_000

OFFLINE_NOTE = (
    "Offline readiness note (LLM_FAKE=1): the deploy adapter runs in simulated mode, "
    "so approving does not create a live environment."
)


async def write_readiness_note(
    request: str,
    design_note: str,
    options: PreviewOptions,
    ws: Workspace,
    usage: LlmUsage,
    on_tool: ToolObserver | None = None,
    on_reasoning: ReasoningObserver | None = None,
) -> str:
    if get_settings().llm_fake:
        return OFFLINE_NOTE
    spec = get_agent_spec(AgentRole.RELEASE_ENGINEER)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Feature request:\n{request}\n\n"
                f"Design note:\n{design_note or '(none)'}\n\n"
                "Preview manifest: "
                f"chart={options.chart_path}, values={options.values_file or 'chart default'}, "
                f"lifetime={options.ttl_hours}h, smoke paths={options.smoke_paths}\n\n"
                "Inspect the diff with git_diff and the chart with your read tools. Reply "
                "with a short plain-text readiness note: what will be deployed, what could "
                "go wrong, and whether anything blocks a preview. No tool call in the final reply."
            ),
        },
    ]
    note = (await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)).strip()
    return note[:MAX_NOTE_CHARS] or "No readiness concerns were reported."
