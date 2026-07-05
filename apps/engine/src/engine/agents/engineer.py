"""Engineer agents: implement one approved task inside the jailed workspace.

The role on the task picks the spec (prompt, model tier, tool allow-list) from
the registry; the shared loop does the rest. With LLM_FAKE=1 the task is
executed deterministically through the same tools — a file is written and
committed — so the pipeline is testable end to end without a model.
"""

from engine.agents.loop import LlmUsage, run_tool_loop
from engine.agents.registry import AgentSpec, get_agent_spec
from engine.agents.supervisor import TaskState
from engine.agents.tools import call_tool
from engine.config import get_settings
from engine.workspace.manager import Workspace


class TaskExecutionError(Exception):
    """The engineer could not complete the task; the supervisor decides retries."""


async def execute_task(task: TaskState, request: str, ws: Workspace, usage: LlmUsage) -> str:
    spec = get_agent_spec(task["role"])
    if get_settings().llm_fake:
        return await _execute_offline(task, spec, ws)

    messages = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Overall feature request:\n{request}\n\n"
                f"Your task (#{task['sequence']}): {task['title']}\n"
                f"Details: {task['description'] or 'none provided'}\n\n"
                "Work only through your tools. Commit your changes with git_commit, "
                "then reply with a short task summary (no tool call) to finish."
            ),
        },
    ]
    return await run_tool_loop(spec, ws, messages, usage)


async def execute_revision(
    role: str, findings: list[str], request: str, ws: Workspace, usage: LlmUsage
) -> str:
    """One revision round: the engineer addresses the Reviewer's findings."""
    spec = get_agent_spec(role)
    if get_settings().llm_fake:
        issues = "\n".join(f"- {finding}" for finding in findings)
        result = await call_tool(
            ws,
            spec.tools,
            "write_file",
            {"path": f".asep/revision-{role}.md", "content": f"# Review findings\n\n{issues}\n"},
        )
        if result.startswith("ERROR:"):
            raise TaskExecutionError(result)
        committed = await call_tool(
            ws, spec.tools, "git_commit", {"message": f"address review findings ({role})"}
        )
        if committed.startswith("ERROR:"):
            raise TaskExecutionError(committed)
        return f"offline revision: addressed {len(findings)} finding(s)"

    issues = "\n".join(f"- {finding}" for finding in findings)
    messages = [
        {"role": "system", "content": spec.system_prompt},
        {
            "role": "user",
            "content": (
                f"Overall feature request:\n{request}\n\n"
                "The Reviewer requested changes to work already committed in this "
                f"workspace. Address every finding below:\n{issues}\n\n"
                "Work only through your tools. Commit your fixes with git_commit, "
                "then reply with a short summary (no tool call) to finish."
            ),
        },
    ]
    return await run_tool_loop(spec, ws, messages, usage)


async def _execute_offline(task: TaskState, spec: AgentSpec, ws: Workspace) -> str:
    """Deterministic offline path: same tools and allow-list, no model."""
    path = f".asep/task-{task['sequence']}.md"
    content = f"# {task['title']}\n\nCompleted offline (LLM_FAKE=1) by the {task['role']} agent.\n"
    for name, args in (
        ("write_file", {"path": path, "content": content}),
        ("git_commit", {"message": f"task {task['sequence']}: {task['title']}"}),
    ):
        result = await call_tool(ws, spec.tools, name, args)
        if result.startswith("ERROR:"):
            raise TaskExecutionError(result)
    return f"offline: wrote and committed {path}"
