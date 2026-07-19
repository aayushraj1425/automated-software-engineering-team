"""The run terminal: one command at a time, inside the sandbox.

ADR-0008's line does not move — the terminal goes *through* the sandbox, not
around it. Each run gets a lazy session container with the same hardening as
the QA sandbox plus one stricter choice: ``--network none`` from birth (no
install phase, no egress, ever). The workspace is copied in, never mounted —
the terminal is a scratch copy; edits there do not reach the real files.
Design note: docs/architecture/IN_BROWSER_TERMINAL.md.
"""

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog

from engine.config import get_settings
from engine.sandbox.runner import _docker, docker_available

log = structlog.get_logger(__name__)

# Mirrors the QA sandbox's caps (sandbox/runner.py).
_MEMORY = "2g"
_CPUS = "2"
_PIDS_LIMIT = "256"

_IMAGE = "python:3.12-slim"  # python + sh covers inspection and pytest alike
_COMMAND_TIMEOUT = 60  # seconds per command
_OUTPUT_TAIL = 8000
MAX_COMMAND_LENGTH = 2000
# A session older than this is discarded before the next command runs —
# checked lazily, so no background reaper is needed.
SESSION_TTL_SECONDS = 30 * 60

_CREATED_LABEL = "asep.terminal.created"


class TerminalUnavailable(Exception):
    """The terminal cannot run here; the message is safe to show."""


@dataclass(frozen=True)
class TerminalResult:
    output: str
    exit_code: int
    fresh_session: bool  # a new container was created for this command


def _container_name(run_id: uuid.UUID) -> str:
    return f"asep-terminal-{run_id.hex[:12]}"


async def _session_age(name: str) -> float | None:
    """Seconds since the session container was created, or None when it is
    not running (missing, exited, or unreadable — all mean 'recreate')."""
    code, out = await _docker(
        "inspect",
        "--format",
        f'{{{{.State.Running}}}} {{{{index .Config.Labels "{_CREATED_LABEL}"}}}}',
        name,
    )
    if code != 0:
        return None
    running, _, created = out.partition(" ")
    if running != "true" or not created.isdigit():
        return None
    return time.time() - int(created)


async def _start_session(name: str, workspace: Path, timeout: int) -> None:
    await _docker("rm", "-f", name)
    code, out = await _docker(
        "run",
        "--detach",
        "--name",
        name,
        # No egress, ever: the terminal has no install phase, so unlike the
        # QA sandbox it never touches a network at all.
        "--network",
        "none",
        "--memory",
        _MEMORY,
        "--cpus",
        _CPUS,
        "--pids-limit",
        _PIDS_LIMIT,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        # Orphans are findable:  docker ps -aq --filter label=asep.terminal
        "--label",
        "asep.terminal=1",
        "--label",
        f"{_CREATED_LABEL}={int(time.time())}",
        "--workdir",
        "/work",
        _IMAGE,
        "sleep",
        "infinity",
        timeout=timeout,  # first run may pull the image
    )
    if code != 0:
        raise TerminalUnavailable(f"could not start the terminal session: {out[-300:]}")
    # Copied, never mounted — commands cannot reach the real workspace.
    code, out = await _docker("cp", os.path.join(workspace, "."), f"{name}:/work", timeout=120)
    if code != 0:
        await _docker("rm", "-f", name)
        raise TerminalUnavailable(f"could not copy the workspace in: {out[-300:]}")


async def run_terminal_command(run_id: uuid.UUID, workspace: Path, command: str) -> TerminalResult:
    """Run one command in the run's session container, creating (or
    refreshing an expired) session first."""
    settings = get_settings()
    if not settings.sandbox_enabled:
        raise TerminalUnavailable(
            "the terminal runs inside the sandbox, which is disabled (SANDBOX_ENABLED=0)"
        )
    if not await docker_available():
        raise TerminalUnavailable("docker is not available — the terminal needs the sandbox")

    name = _container_name(run_id)
    age = await _session_age(name)
    fresh = age is None or age > SESSION_TTL_SECONDS
    if fresh:
        await _start_session(name, workspace, settings.sandbox_timeout_seconds)

    code, out = await _docker("exec", name, "sh", "-c", command, timeout=_COMMAND_TIMEOUT)
    if code == -1:
        # The command may still be running inside; discard the session so the
        # next command starts clean instead of queueing behind it.
        await _docker("rm", "-f", name)
        return TerminalResult(
            output=f"(command timed out after {_COMMAND_TIMEOUT}s — the session was reset)",
            exit_code=-1,
            fresh_session=fresh,
        )
    log.info("terminal.command", run_id=str(run_id), exit_code=code)
    return TerminalResult(output=out[-_OUTPUT_TAIL:], exit_code=code, fresh_session=fresh)


async def reset_terminal(run_id: uuid.UUID) -> None:
    """Discard the run's session container (the next command starts fresh)."""
    await _docker("rm", "-f", _container_name(run_id))
