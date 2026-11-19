"""Principal Engineer agent: the design note before planning, the final diff review after.

Read-only by registry policy (no write or commit tools). The design note is plain
markdown the Product Manager plans from and the final review checks the diff against.
The review answers in the same verdict JSON as the Reviewer, so the runner's single
revision round works for both. With LLM_FAKE=1 both steps are fixed and deterministic.
"""

from typing import Any

from engine.agents.loop import LlmUsage, ReasoningObserver, ToolObserver, run_tool_loop
from engine.agents.registry import get_agent_spec
from engine.agents.reviewer import (
    APPROVE,
    VERDICT_FORMAT,
    ReviewError,
    parse_verdict,
    validate_verdict,
)
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.workspace.manager import Workspace

MAX_DESIGN_NOTE_CHARS = 12_000

OFFLINE_DESIGN_NOTE = (
    "## Design note (offline, LLM_FAKE=1)\n\n"
    "- Keep each service change behind its existing interface.\n"
    "- Split the work by service; the hardest task goes to a Senior Engineer.\n"
    "- Acceptance: the repository tests pass and the diff stays within the plan."
)


class DesignNoteError(Exception):
    """The Principal returned no usable design note."""


async def write_design_note(
    request: str,
    ws: Workspace,
    usage: LlmUsage,
    on_tool: ToolObserver | None = None,
    on_reasoning: ReasoningObserver | None = None,
    memory: str = "",
) -> str:
    if get_settings().llm_fake:
        return OFFLINE_DESIGN_NOTE
    spec = get_agent_spec(AgentRole.PRINCIPAL_ENGINEER)
    memory_block = f"{memory}\n\n" if memory else ""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"{memory_block}Feature request:\n{request}\n\n"
                "Read the repository with your tools, then reply with a design note in "
                "markdown: the affected services and files, the interfaces that must not "
                "change, risks (migrations, security, rollout), how the work should be "
                "split, which parts are hard enough for a Senior Engineer, and the "
                "acceptance criteria. Reply with the note only, no tool call."
            ),
        },
    ]
    note = (await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)).strip()
    if not note:
        raise DesignNoteError("the Principal Engineer returned an empty design note")
    return note[:MAX_DESIGN_NOTE_CHARS]


async def review_against_design(
    request: str,
    plan_summary: str,
    design_note: str,
    ws: Workspace,
    usage: LlmUsage,
    on_tool: ToolObserver | None = None,
    on_reasoning: ReasoningObserver | None = None,
) -> dict[str, Any]:
    if get_settings().llm_fake:
        return {"verdict": APPROVE, "findings": []}
    spec = get_agent_spec(AgentRole.PRINCIPAL_ENGINEER)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Feature request:\n{request}\n\n"
                f"Design note you wrote:\n{design_note or '(none)'}\n\n"
                f"Approved plan summary:\n{plan_summary}\n\n"
                "Final review: start with git_diff, read the touched files, and check "
                "that the diff follows the design note and its acceptance criteria.\n\n"
                f"{VERDICT_FORMAT}"
            ),
        },
    ]
    reply = await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)
    try:
        return validate_verdict(parse_verdict(reply))
    except ReviewError as exc:
        messages.append(
            {"role": "user", "content": f"That verdict was rejected: {exc}\n\n{VERDICT_FORMAT}"}
        )
        reply = await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)
        return validate_verdict(parse_verdict(reply))
