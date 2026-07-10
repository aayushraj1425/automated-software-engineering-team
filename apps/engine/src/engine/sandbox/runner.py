"""Runs a workspace's tests inside a disposable Docker container.

The container is the one place agent-written code executes (ADR-0008). The
workspace is *copied* in — never mounted — so tests cannot touch the real
files; dependencies install with the network on, then the network is
disconnected before the tests run; the container is removed no matter what.

Design note: docs/architecture/SANDBOX_EXECUTION.md.
"""

import asyncio
import json
import os
import subprocess
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)

# Hard resource limits for every sandbox container.
_MEMORY = "2g"
_CPUS = "2"
_PIDS_LIMIT = "256"

# How much captured output a result keeps — enough to read a test failure,
# small enough to store on a timeline event.
_OUTPUT_TAIL = 4000

# Directories that never contain the *run's* tests — skipped when probing for
# bare test files so a vendored dependency cannot trigger (or slow down) a run.
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}

SandboxStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True)
class SandboxPlan:
    """What to run for this workspace, decided by looking at its files."""

    image: str
    install: str | None  # runs with the network ON (package downloads)
    test: str  # runs with the network OFF


@dataclass(frozen=True)
class SandboxResult:
    status: SandboxStatus
    reason: str  # why it failed or was skipped; "" when passed
    output: str  # tail of the captured install/test output
    exit_code: int | None  # of the test command; None when it never ran
    plan: SandboxPlan | None  # what would have / did run


def detect_plan(workspace: Path) -> SandboxPlan | None:
    """Pick the build-and-test plan from the files present, or None.

    Deliberately small: recognized stacks get a fixed, known command — the
    sandbox never executes a command an agent wrote into a config file.
    """
    if (workspace / "requirements.txt").is_file():
        return SandboxPlan(
            image="python:3.12-slim",
            install="pip install -q -r requirements.txt pytest",
            test="python -m pytest -q",
        )
    if (workspace / "pyproject.toml").is_file():
        # Only `pip install .` a pyproject that actually builds a package. Many
        # repos carry pyproject.toml purely for tool config ([tool.ruff],
        # [tool.pytest.ini_options], …) with no [project]/[build-system]; for
        # those `pip install .` errors out and would falsely fail the run.
        installable = _pyproject_is_installable(workspace / "pyproject.toml")
        install = "pip install -q . pytest" if installable else "pip install -q pytest"
        return SandboxPlan(
            image="python:3.12-slim",
            install=install,
            test="python -m pytest -q",
        )
    if (workspace / "package.json").is_file():
        if _package_json_has_test_script(workspace / "package.json"):
            install = "npm ci" if (workspace / "package-lock.json").is_file() else "npm install"
            return SandboxPlan(image="node:20-slim", install=install, test="npm test")
        return None
    if _has_bare_python_tests(workspace):
        return SandboxPlan(
            image="python:3.12-slim",
            install="pip install -q pytest",
            test="python -m pytest -q",
        )
    return None


def _pyproject_is_installable(path: Path) -> bool:
    """True when pyproject.toml declares an actual package (a [project] or a
    [build-system] table), so `pip install .` can build it. A pyproject that
    only carries tool config is not installable."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return False
    return isinstance(data, dict) and ("project" in data or "build-system" in data)


def _package_json_has_test_script(path: Path) -> bool:
    """True when package.json really declares a test script (parsed, not grepped)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return isinstance(scripts, dict) and bool(scripts.get("test"))


def _has_bare_python_tests(workspace: Path) -> bool:
    """Look for test_*.py files, skipping directories that never hold the run's
    own tests (.git, node_modules, virtualenvs, build output)."""
    stack = [workspace]
    while stack:
        folder = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.name.startswith("test_") and entry.name.endswith(".py"):
                return True
    return False


async def _docker(*args: str, timeout: int = 60) -> tuple[int, str]:
    """One docker CLI call → (exit code, combined output).

    Runs in a thread with blocking subprocess for the same reason as run_git:
    the Windows Selector event loop (psycopg needs it) cannot spawn async
    subprocesses.
    """

    def _run() -> tuple[int, str]:
        try:
            proc = subprocess.run(  # noqa: S603 — fixed executable, no shell
                ["docker", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return -1, f"timed out after {timeout}s"
        except FileNotFoundError:
            return -2, "docker is not installed"
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace").strip()

    return await asyncio.to_thread(_run)


async def docker_available() -> bool:
    """True when a Docker daemon answers (Docker Desktop running)."""
    code, _ = await _docker("version", "--format", "{{.Server.Version}}", timeout=20)
    return code == 0


async def run_sandbox(workspace: Path, run_id: uuid.UUID) -> SandboxResult:
    """Copy the workspace into a fresh container, install, unplug, test, delete."""
    settings = get_settings()
    if not settings.sandbox_enabled:
        return SandboxResult("skipped", "sandbox disabled (SANDBOX_ENABLED=0)", "", None, None)

    plan = detect_plan(workspace)
    if plan is None:
        return SandboxResult("skipped", "no recognized test setup in the workspace", "", None, plan)

    if not await docker_available():
        if settings.sandbox_required:
            # Strict mode: a missing sandbox must never silently wave code through.
            return SandboxResult(
                "failed", "docker is not available and SANDBOX_REQUIRED=1", "", None, plan
            )
        return SandboxResult("skipped", "docker is not available", "", None, plan)

    name = f"asep-sandbox-{run_id.hex[:12]}"
    timeout = settings.sandbox_timeout_seconds
    try:
        return await _execute(plan, workspace, name, timeout)
    finally:
        await _docker("rm", "-f", name)  # always, even after an exception


async def _execute(plan: SandboxPlan, workspace: Path, name: str, timeout: int) -> SandboxResult:
    # A long sleep keeps the container alive between the exec phases; it is
    # force-removed at the end, so the sleep never actually finishes.
    code, out = await _docker(
        "run",
        "--detach",
        "--name",
        name,
        "--memory",
        _MEMORY,
        "--cpus",
        _CPUS,
        "--pids-limit",
        _PIDS_LIMIT,
        # Hardening: the code inside never needs kernel capabilities, and must
        # not gain new privileges via setuid binaries.
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        # Label makes orphaned containers findable if the engine dies mid-run:
        #   docker ps -aq --filter label=asep.sandbox | xargs docker rm -f
        "--label",
        "asep.sandbox=1",
        "--workdir",
        "/work",
        plan.image,
        "sleep",
        "infinity",
        timeout=timeout,  # first run may pull the image
    )
    if code != 0:
        return SandboxResult(
            "failed", "could not start the sandbox container", _tail(out), None, plan
        )

    # Copy the files in; nothing is mounted, so tests cannot reach the workspace.
    code, out = await _docker("cp", os.path.join(workspace, "."), f"{name}:/work", timeout=120)
    if code != 0:
        return SandboxResult("failed", "could not copy the workspace in", _tail(out), None, plan)

    install_out = ""
    if plan.install is not None:
        code, install_out = await _docker("exec", name, "sh", "-c", plan.install, timeout=timeout)
        if code != 0:
            return SandboxResult(
                "failed", "dependency install failed", _tail(install_out), None, plan
            )

    # Unplug the network: from here on the agent-written code runs with no egress.
    code, out = await _docker("network", "disconnect", "bridge", name)
    if code != 0:
        return SandboxResult("failed", "could not disconnect the network", _tail(out), None, plan)

    code, test_out = await _docker("exec", name, "sh", "-c", plan.test, timeout=timeout)
    output = _tail(f"{install_out}\n{test_out}".strip())
    if code == -1:
        return SandboxResult("failed", f"tests timed out after {timeout}s", output, None, plan)
    if code != 0:
        return SandboxResult("failed", f"tests failed (exit code {code})", output, code, plan)
    log.info("sandbox.passed", container=name, image=plan.image)
    return SandboxResult("passed", "", output, 0, plan)


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL:]
