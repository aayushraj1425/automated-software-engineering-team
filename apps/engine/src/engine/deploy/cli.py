"""The only place the adapter starts a process: fixed tools, argument lists, no shell.

Runs in a thread with blocking subprocess for the same reason workspace/manager.py
does: the engine uses the Windows Selector event loop, which cannot spawn async
subprocesses. The child gets an allow-listed environment, so engine secrets
(database URL, service secret, provider keys) are never inherited.
"""

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from engine.deploy.safety import PreviewError

ALLOWED_TOOLS = frozenset({"helm", "kubectl"})
MAX_OUTPUT_BYTES = 5_000_000
_PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "SystemRoot", "PATHEXT", "COMSPEC", "LANG", "LC_ALL")


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str


def tool_available(tool: str) -> bool:
    return tool in ALLOWED_TOOLS and shutil.which(tool) is not None


def build_env(workdir: Path, kubeconfig: Path | None) -> dict[str, str]:
    """A minimal environment. Helm and kubectl state live under `workdir`."""
    env = {key: os.environ[key] for key in _PASSTHROUGH_ENV if key in os.environ}
    state = workdir / "state"
    for name in ("helm-cache", "helm-config", "helm-data", "helm-plugins", "kube-cache", "home"):
        (state / name).mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(state / "home")
    env["USERPROFILE"] = str(state / "home")
    env["HELM_CACHE_HOME"] = str(state / "helm-cache")
    env["HELM_CONFIG_HOME"] = str(state / "helm-config")
    env["HELM_DATA_HOME"] = str(state / "helm-data")
    env["HELM_PLUGINS"] = str(state / "helm-plugins")
    env["KUBECACHEDIR"] = str(state / "kube-cache")
    env["HELM_DEBUG"] = "false"
    if kubeconfig is not None:
        env["KUBECONFIG"] = str(kubeconfig)
    return env


async def run_cli(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    cwd: Path,
    input_text: str | None = None,
) -> CliResult:
    """Run `helm ...` or `kubectl ...`. argv[0] must be one of ALLOWED_TOOLS."""
    if not argv or argv[0] not in ALLOWED_TOOLS:
        raise PreviewError("internal: only helm and kubectl may be run")
    if any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
        raise PreviewError("internal: invalid command argument")
    exe = shutil.which(argv[0])
    if exe is None:
        raise PreviewError(f"{argv[0]} is not installed on the engine host")
    command = [exe, *argv[1:]]

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - fixed executable, argument list, no shell
            command,
            cwd=cwd,
            env=env,
            input=input_text.encode("utf-8") if input_text is not None else None,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        raise PreviewError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} timed out") from None
    except OSError:
        raise PreviewError(f"{argv[0]} could not be started") from None
    return CliResult(
        returncode=proc.returncode,
        stdout=proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        stderr=proc.stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
    )
