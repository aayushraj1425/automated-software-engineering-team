"""Tool-call probes: small, fixed checks that a model can drive agent tools.

Open source models are the weakest at structured tool calls, so a model must pass
every probe (and the golden tasks) before auto selection may use it. The probes
talk to the model only through a caller supplied `complete` function, so unit
tests use stubs and the evaluation script passes the real ModelRouter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the router imports llm/evidence, which imports this module
    from engine.llm.router import AssistantTurn, ToolCall

Complete = Callable[[list[dict[str, Any]], list[dict[str, Any]]], "Awaitable[AssistantTurn]"]

MAX_TURNS = 3

PROBE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one shell command in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "description": "Seconds, whole number"},
                },
                "required": ["command", "timeout_seconds"],
            },
        },
    },
]

SYSTEM = "You are a coding agent. Use the provided tools when you need to act."


@dataclass(frozen=True)
class ProbeResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Probe:
    name: str
    prompt: str
    judge: Callable[[list[ToolCall], str], tuple[bool, str]]
    expect_tools: bool = True


def _single_read(calls: list[ToolCall], _text: str) -> tuple[bool, str]:
    if len(calls) != 1 or calls[0].name != "read_file":
        return False, f"expected exactly one read_file call, got {[c.name for c in calls]}"
    path = calls[0].arguments.get("path")
    return (path == "src/app.py", f"read_file path was {path!r}")


def _typed_arguments(calls: list[ToolCall], _text: str) -> tuple[bool, str]:
    runs = [c for c in calls if c.name == "run_command"]
    if len(runs) != 1:
        return False, f"expected one run_command call, got {[c.name for c in calls]}"
    args = runs[0].arguments
    timeout = args.get("timeout_seconds")
    command = args.get("command")
    ok = (
        isinstance(timeout, int)
        and not isinstance(timeout, bool)
        and timeout == 90
        and isinstance(command, str)
        and "pytest" in command
    )
    return ok, f"command={command!r} timeout_seconds={timeout!r}"


def _both_files(calls: list[ToolCall], _text: str) -> tuple[bool, str]:
    paths = {c.arguments.get("path") for c in calls if c.name == "read_file"}
    return paths >= {"a.py", "b.py"}, f"read paths: {sorted(map(str, paths))}"


def _no_tool_needed(calls: list[ToolCall], text: str) -> tuple[bool, str]:
    if calls:
        return False, f"called {[c.name for c in calls]} when no tool was needed"
    return "4" in text, "answered without a tool"


PROBES: tuple[Probe, ...] = (
    Probe("single_call", "Read the file src/app.py.", _single_read),
    Probe(
        "typed_arguments",
        "Run `pytest -q` with a timeout of 90 seconds.",
        _typed_arguments,
    ),
    Probe(
        "several_calls",
        "Read both a.py and b.py. Use the tool for each file, then say done.",
        _both_files,
    ),
    Probe(
        "no_tool_when_unneeded",
        "What is 2 + 2? Answer in one short sentence without using any tool.",
        _no_tool_needed,
        expect_tools=False,
    ),
)


def probes_digest() -> str:
    """Changes whenever a probe prompt or the tool schemas change."""
    payload = json.dumps(
        {"tools": PROBE_TOOLS, "system": SYSTEM, "probes": [(p.name, p.prompt) for p in PROBES]},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class _Transcript:
    messages: list[dict[str, Any]]
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""


async def run_probe(probe: Probe, complete: Complete) -> ProbeResult:
    """Drive one probe for up to MAX_TURNS, feeding back plain tool results."""
    transcript = _Transcript(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": probe.prompt}]
    )
    try:
        for _ in range(MAX_TURNS):
            turn = await complete(transcript.messages, PROBE_TOOLS)
            transcript.text += turn.content or ""
            transcript.messages.append(turn.message)
            if not turn.tool_calls:
                break
            transcript.calls.extend(turn.tool_calls)
            for call in turn.tool_calls:
                transcript.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": "ok"}
                )
            if probe.name != "several_calls":
                break  # one tool round is enough for the single-shot probes
        passed, detail = probe.judge(transcript.calls, transcript.text)
    except Exception as error:  # a provider failure is a failed probe, not a crash
        return ProbeResult(probe.name, False, f"{type(error).__name__}: {str(error)[:200]}")
    return ProbeResult(probe.name, passed, detail[:300])


async def run_probes(complete: Complete) -> list[ProbeResult]:
    return [await run_probe(probe, complete) for probe in PROBES]
