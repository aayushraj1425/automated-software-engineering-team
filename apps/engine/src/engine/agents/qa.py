"""QA agent: fix the code when the sandbox tests fail, so the run can retry.

The sandbox (engine/sandbox/runner.py) reports a failure with the captured test
output; the QA agent reads that output, edits the workspace to fix the real
defect, and commits — then the runner re-runs the sandbox. The prompt forbids
gaming the tests (deleting/skipping/weakening them). With LLM_FAKE=1 the fix is
a deterministic commit so the loop is testable without a model. Design note:
docs/architecture/QA_AGENT.md.
"""

from engine.agents.loop import LlmUsage, ReasoningObserver, ToolObserver, run_tool_loop
from engine.agents.registry import get_agent_spec
from engine.config import get_settings
from engine.db.enums import AgentRole
from engine.workspace.manager import Workspace

# The failing sandbox output can be large; keep the tail the model reads bounded.
_FAILURE_TAIL = 4000


async def fix_failing_tests(
    request: str,
    failure_output: str,
    ws: Workspace,
    usage: LlmUsage,
    attempt: int,
    max_attempts: int,
    on_tool: ToolObserver | None = None,
    on_reasoning: ReasoningObserver | None = None,
) -> str:
    """One QA fix-and-commit round against the current sandbox failure."""
    spec = get_agent_spec(AgentRole.QA)
    if get_settings().llm_fake:
        return await _fix_offline(ws, attempt, on_tool)

    failure = failure_output[-_FAILURE_TAIL:]
    messages = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Overall feature request:\n{request}\n\n"
                f"This is QA fix attempt {attempt} of {max_attempts}. The change "
                "committed in this workspace failed its tests in the sandbox. "
                f"Captured test output (tail):\n\n{failure}\n\n"
                "Fix the code so the tests pass, commit with git_commit, then "
                "reply with a short summary (no tool call) to finish."
            ),
        },
    ]
    return await run_tool_loop(spec, ws, messages, usage, on_tool, on_reasoning)


async def _fix_offline(ws: Workspace, attempt: int, on_tool: ToolObserver | None) -> str:
    """Deterministic offline path: same tools, no model — commit a note so the
    loop advances and the re-run can be driven by a faked sandbox. The path is
    attempt-specific so each round is a real, committable change."""
    from engine.agents.engineer import _run_offline_steps

    spec = get_agent_spec(AgentRole.QA)
    path = f".asep/qa-fix-{attempt}.md"
    steps = (
        ("write_file", {"path": path, "content": f"# QA fix (attempt {attempt})\n\nLLM_FAKE=1.\n"}),
        ("git_commit", {"message": f"qa: fix attempt {attempt}"}),
    )
    await _run_offline_steps(spec, ws, steps, on_tool)
    return f"offline QA: committed fix attempt {attempt}"
