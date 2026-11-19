"""Release Engineer functions: readiness check, preview release, PR evidence, cleanup.

Plain async functions the runner calls. They never touch the database and never
see a model: credentials arrive already decrypted from the runner and go straight
to the deploy adapter. Approval gating belongs to the runner, not here
(PREVIEW_DEPLOY_ADAPTER.md).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from engine.deploy.contracts import PreviewDeployment, PreviewOptions, SmokeResult
from engine.deploy.preview import (
    SweepResult,
    check_chart,
    deploy_preview,
    is_expired,
    run_cloud_smoke_tests,
    sweep_expired_previews,
    teardown_preview,
    teardown_preview_for_run,
)
from engine.workspace.manager import Workspace

__all__ = [
    "ReleaseReadiness",
    "SweepResult",
    "assess_release_readiness",
    "cleanup_preview",
    "format_deploy_evidence",
    "is_expired",
    "run_preview_release",
    "sweep_expired_previews",
    "teardown_preview",
    "teardown_preview_for_run",
]

# on_event(name, payload): the runner records deploy.started / deploy.finished.
EventSink = Callable[[str, dict], Awaitable[None]]


@dataclass(frozen=True)
class ReleaseReadiness:
    ready: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rendered: bool = False


async def assess_release_readiness(
    ws: Workspace, options: PreviewOptions | None = None
) -> ReleaseReadiness:
    """What the human sees before approving: would the adapter accept this chart?

    Read-only, no credentials, no cluster.
    """
    report = await check_chart(ws.path, options, run_id=ws.run_id)
    return ReleaseReadiness(
        ready=report.ok,
        problems=report.problems,
        notes=report.notes,
        rendered=report.rendered,
    )


async def run_preview_release(
    ws: Workspace,
    credentials: dict[str, str],
    *,
    options: PreviewOptions | None = None,
    expected_sha: str | None = None,
    on_event: EventSink | None = None,
) -> PreviewDeployment:
    """Deploy, then smoke test. Returns one deployment with `smoke` filled in.

    The caller has already enforced the second human approval and passes the
    approved commit as `expected_sha`. A failed smoke test leaves the preview up
    for inspection until its TTL or an explicit cleanup_preview.
    """
    opts = options or PreviewOptions()

    async def emit(name: str, payload: dict) -> None:
        if on_event is not None:
            await on_event(name, payload)

    await emit("deploy.started", {"run_id": str(ws.run_id), "ttl_hours": opts.ttl_hours})
    deployment = await deploy_preview(ws, credentials, options=opts, expected_sha=expected_sha)

    smoke: SmokeResult | None = deployment.smoke
    if deployment.status == "deployed":
        if deployment.url:
            smoke = await run_cloud_smoke_tests(deployment.url, paths=opts.smoke_paths)
        else:
            smoke = SmokeResult(
                passed=False, error="the chart exposed no Ingress host or LoadBalancer address"
            )
    deployment = deployment.model_copy(update={"smoke": smoke})
    await emit(
        "deploy.finished",
        {
            "run_id": str(ws.run_id),
            "status": deployment.status,
            "simulated": deployment.status == "simulated",
            "url": deployment.url,
            "expires_at": deployment.expires_at.isoformat(),
            "smoke_passed": smoke.passed if smoke is not None else None,
            "error": deployment.error,
        },
    )
    return deployment


async def cleanup_preview(
    deployment: PreviewDeployment, credentials: dict[str, str]
) -> PreviewDeployment:
    """Tear the preview down and return the record marked deleted (idempotent)."""
    await teardown_preview(deployment, credentials)
    if deployment.status == "simulated":
        return deployment
    return deployment.model_copy(update={"status": "deleted", "url": None})


def _cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ")[:120]


def format_deploy_evidence(deployment: PreviewDeployment) -> str:
    """Markdown for the PR body. Simulated runs are labelled as not real."""
    lines = ["### Preview deployment"]
    if deployment.status == "simulated":
        lines += [
            "",
            "**SIMULATED.** Offline mode: nothing was deployed, there is no preview URL, "
            "and no smoke tests ran. This is not evidence that the change works in a cluster.",
        ]
        return "\n".join(lines)
    lines.append("")
    lines.append(f"- Status: **{deployment.status}**")
    if deployment.source_sha:
        lines.append(f"- Commit: `{deployment.source_sha[:12]}`")
    if deployment.url:
        lines.append(f"- URL: {deployment.url}")
    lines.append(f"- Namespace: `{deployment.namespace}`")
    lines.append(f"- Expires: {deployment.expires_at.isoformat()}")
    if deployment.error:
        lines.append(f"- Error: {_cell(deployment.error)}")
    smoke = deployment.smoke
    if smoke is not None:
        verdict = "passed" if smoke.passed else "FAILED"
        lines += ["", f"Cloud smoke tests: **{verdict}**"]
        if smoke.error:
            lines.append(f"({_cell(smoke.error)})")
        if smoke.checks:
            lines += ["", "| Path | Status | Result | Attempts |", "| --- | --- | --- | --- |"]
            for check in smoke.checks:
                result = "ok" if check.get("ok") else _cell(check.get("error") or "failed")
                lines.append(
                    f"| `{_cell(check.get('path'))}` | {_cell(check.get('status'))} "
                    f"| {result} | {_cell(check.get('attempts', 1))} |"
                )
    return "\n".join(lines)
