"""Preview deployments to a Kubernetes namespace with Helm. Never production.

Public surface (the contract in contracts.py):
    deploy_preview, run_cloud_smoke_tests, teardown_preview
plus cleanup hooks: is_expired, teardown_preview_for_run, sweep_expired_previews,
and check_chart (the credential-free chart check used by the release agent).

Credentials never leave this package. The kubeconfig text is rebuilt into a clean
temp file, used by helm and kubectl only, and deleted when the call ends.
Design note: docs/architecture/agents/PREVIEW_DEPLOY_ADAPTER.md.
"""

import contextlib
import json
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import structlog
import yaml

from engine.config import get_settings
from engine.deploy import chart as chartmod
from engine.deploy import cli, smoke
from engine.deploy.contracts import PreviewDeployment, PreviewOptions, SmokeResult
from engine.deploy.frozen import freeze_checked_manifests
from engine.deploy.kubeconfig import SafeKubeconfig, sanitize_kubeconfig
from engine.deploy.safety import PreviewError, scrub
from engine.deploy.settings import get_preview_settings
from engine.workspace.manager import Workspace, WorkspaceError, run_git

log = structlog.get_logger(__name__)

NAMESPACE_PREFIX = "asep-preview-"
RELEASE_PREFIX = "preview-"
LABEL_MANAGED = "asep.io/managed-by"
LABEL_RUN = "asep.io/preview-run-id"
ANNOTATION_EXPIRES = "asep.io/expires-at"
MANAGED_VALUE = "asep-preview"
KUBECTL_REQUEST_TIMEOUT = "30s"

_NAMESPACE_RE = re.compile(r"^asep-preview-[0-9a-f]{32}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-:@]{0,254}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def is_simulated() -> bool:
    """Offline simulation is tied to LLM_FAKE and nothing else."""
    return get_settings().llm_fake


def preview_namespace(run_id: uuid.UUID) -> str:
    return f"{NAMESPACE_PREFIX}{run_id.hex}"


def preview_release(run_id: uuid.UUID) -> str:
    return f"{RELEASE_PREFIX}{run_id.hex}"


def is_expired(deployment: PreviewDeployment, now: datetime | None = None) -> bool:
    expires = deployment.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= (now or _utcnow())


def _check_options(options: PreviewOptions) -> None:
    if options.image is not None and (
        not _IMAGE_RE.match(options.image) or ".." in options.image or "//" in options.image
    ):
        raise PreviewError("options.image is not a valid image reference")
    smoke.validate_paths(options.smoke_paths)


# ---------------------------------------------------------------- sessions


class _Session:
    """A private temp folder with the rebuilt kubeconfig, plus helm/kubectl helpers."""

    def __init__(self, credentials: dict[str, str]) -> None:
        prefs = get_preview_settings()
        raw = credentials.get("kubeconfig") if isinstance(credentials, dict) else None
        self.kube: SafeKubeconfig = sanitize_kubeconfig(
            raw or "",
            allow_local_cluster=prefs.preview_allow_local_cluster,
            allowed_api_hosts=prefs.allowed_api_server_hosts,
        )
        self.dir = Path(tempfile.mkdtemp(prefix="asep-preview-"))
        self.timeout = max(30, prefs.preview_helm_timeout_seconds)
        kubeconfig = self.dir / "kubeconfig"
        kubeconfig.write_text(self.kube.text, encoding="utf-8")
        with contextlib.suppress(OSError):
            kubeconfig.chmod(0o600)
        self.env = cli.build_env(self.dir, kubeconfig)

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    async def run(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> cli.CliResult:
        try:
            result = await cli.run_cli(
                argv,
                env=self.env,
                timeout=timeout or self.timeout + 60,
                cwd=self.dir,
                input_text=input_text,
            )
        except PreviewError as exc:
            raise PreviewError(scrub(str(exc), self.kube.secrets)) from None
        if check and result.returncode != 0:
            detail = scrub(result.stderr or result.stdout, self.kube.secrets)
            raise PreviewError(f"{argv[0]} {argv[1]} failed: {detail}")
        return result

    def kubectl(self, *args: str, **kw: Any):
        return self.run(["kubectl", f"--request-timeout={KUBECTL_REQUEST_TIMEOUT}", *args], **kw)

    def helm(self, *args: str, **kw: Any):
        return self.run(["helm", *args], **kw)


def _not_found(result: cli.CliResult) -> bool:
    text = f"{result.stderr}\n{result.stdout}".lower()
    return "notfound" in text or "not found" in text


# ------------------------------------------------------------ chart checking


@dataclass
class ChartReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rendered: bool = False

    def summary(self) -> str:
        head = "chart accepted" if self.ok else "chart rejected"
        lines = [head, *(f"- {p}" for p in self.problems), *(f"note: {n}" for n in self.notes)]
        return "\n".join(lines)


def _overlay_values(
    run_id: uuid.UUID, options: PreviewOptions, expires_at: datetime
) -> dict[str, Any]:
    overlay: dict[str, Any] = {
        "preview": {
            "enabled": True,
            "runId": run_id.hex,
            "namespace": preview_namespace(run_id),
            "release": preview_release(run_id),
            "ttlHours": options.ttl_hours,
            "expiresAt": expires_at.isoformat(),
        }
    }
    if options.image:
        overlay["image"] = options.image
    return overlay


def _template_args(
    run_id: uuid.UUID, staged: chartmod.StagedChart, overlay_file: Path
) -> list[str]:
    args = ["template", preview_release(run_id), str(staged.chart_dir)]
    args += ["--namespace", preview_namespace(run_id), "--skip-tests"]
    if staged.values_file is not None:
        args += ["--values", str(staged.values_file)]
    args += ["--values", str(overlay_file)]
    return args


async def _render_and_check(
    work: Path,
    run_id: uuid.UUID,
    staged: chartmod.StagedChart,
    options: PreviewOptions,
    expires_at: datetime,
) -> str:
    """helm template with NO credentials and no cluster, then the manifest policy."""
    overlay_file = work / "preview-overlay.yaml"
    overlay_file.write_text(
        yaml.safe_dump(_overlay_values(run_id, options, expires_at)), encoding="utf-8"
    )
    env = cli.build_env(work, None)
    result = await cli.run_cli(
        ["helm", *_template_args(run_id, staged, overlay_file)],
        env=env,
        timeout=90,
        cwd=work,
    )
    if result.returncode != 0:
        raise PreviewError(f"helm template failed: {scrub(result.stderr or result.stdout)}")
    problems = chartmod.check_rendered_manifests(
        result.stdout,
        preview_namespace(run_id),
        get_preview_settings().allowed_image_registries,
    )
    if problems:
        raise PreviewError("chart rejected: " + "; ".join(problems[:8]))
    return result.stdout


async def _helm_rollback_flag(work: Path) -> str:
    result = await cli.run_cli(
        ["helm", "upgrade", "--help"], env=cli.build_env(work, None), timeout=30, cwd=work
    )
    if result.returncode == 0:
        if "--rollback-on-failure" in result.stdout:
            return "--rollback-on-failure"
        if "--atomic" in result.stdout:
            return "--atomic"
    raise PreviewError("Helm does not advertise a supported rollback-on-failure option")


async def check_chart(
    workspace_root: Path,
    options: PreviewOptions | None = None,
    *,
    run_id: uuid.UUID | None = None,
    render: bool = True,
) -> ChartReport:
    """Credential-free chart check: static rules, plus render policy if Helm exists."""
    opts = options or PreviewOptions()
    rid = run_id or uuid.UUID(int=0)
    work = Path(tempfile.mkdtemp(prefix="asep-chartcheck-"))
    try:
        try:
            _check_options(opts)
            staged = chartmod.stage_chart(workspace_root, opts.chart_path, opts.values_file, work)
        except PreviewError as exc:
            return ChartReport(ok=False, problems=[str(exc)])
        problems = chartmod.static_check(staged)
        if problems:
            return ChartReport(ok=False, problems=problems)
        report = ChartReport(ok=True)
        if not render:
            report.notes.append("render check skipped")
        elif not cli.tool_available("helm"):
            report.notes.append(
                "helm is not installed here, so the rendered-manifest policy was NOT checked"
            )
        else:
            try:
                await _render_and_check(
                    work, rid, staged, opts, _utcnow() + timedelta(hours=opts.ttl_hours)
                )
                report.rendered = True
            except PreviewError as exc:
                return ChartReport(ok=False, problems=[str(exc)])
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------ source checks


async def _verified_head(ws: Workspace, options: PreviewOptions, expected: str | None) -> str:
    """The commit being deployed. The tree must match it exactly."""
    try:
        head = await run_git(ws.path, "rev-parse", "HEAD")
        dirty = await run_git(ws.path, "status", "--porcelain", "--untracked-files=no")
        pathspecs = [options.chart_path] + ([options.values_file] if options.values_file else [])
        untracked = await run_git(ws.path, "status", "--porcelain", "--", *pathspecs)
    except WorkspaceError:
        raise PreviewError("could not read the workspace commit") from None
    if dirty or untracked:
        raise PreviewError("the workspace has uncommitted changes; commit before deploying")
    if expected is not None:
        wanted = expected.strip().lower()
        if len(wanted) < 7 or not head.lower().startswith(wanted):
            raise PreviewError("the workspace commit is not the approved commit")
    return head


# ----------------------------------------------------------------- deploy


def _namespace_manifest(run_id: uuid.UUID, expires_at: datetime) -> str:
    ns = preview_namespace(run_id)
    docs = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": ns,
                "labels": {
                    LABEL_MANAGED: MANAGED_VALUE,
                    LABEL_RUN: run_id.hex,
                    "pod-security.kubernetes.io/enforce": "baseline",
                },
                "annotations": {ANNOTATION_EXPIRES: expires_at.isoformat()},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "asep-preview-quota", "namespace": ns},
            "spec": {
                "hard": {
                    "pods": "20",
                    "services": "10",
                    "services.loadbalancers": "1",
                    "persistentvolumeclaims": "5",
                    "requests.cpu": "4",
                    "requests.memory": "8Gi",
                    "limits.cpu": "8",
                    "limits.memory": "16Gi",
                }
            },
        },
        {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {"name": "asep-preview-defaults", "namespace": ns},
            "spec": {
                "limits": [
                    {
                        "type": "Container",
                        "default": {"cpu": "500m", "memory": "512Mi"},
                        "defaultRequest": {"cpu": "100m", "memory": "128Mi"},
                    }
                ]
            },
        },
    ]
    return yaml.safe_dump_all(docs)


async def _get_namespace(session: _Session, run_id: uuid.UUID) -> dict | None:
    """The namespace object, or None when it does not exist. Refuses foreign ones."""
    ns = preview_namespace(run_id)
    result = await session.kubectl("get", "namespace", ns, "-o", "json", check=False)
    if result.returncode != 0:
        if _not_found(result):
            return None
        raise PreviewError(
            f"kubectl get failed: {scrub(result.stderr or result.stdout, session.kube.secrets)}"
        )
    try:
        obj = json.loads(result.stdout)
    except ValueError:
        raise PreviewError("kubectl returned unreadable namespace data") from None
    labels = (obj.get("metadata") or {}).get("labels") or {}
    if labels.get(LABEL_MANAGED) != MANAGED_VALUE or labels.get(LABEL_RUN) != run_id.hex:
        raise PreviewError("the namespace exists but is not a preview created by this platform")
    return obj


def discover_url(ingress_json: str, services_json: str) -> str | None:
    """The preview's public URL from Ingress hosts, else a LoadBalancer address."""
    try:
        ingresses = json.loads(ingress_json).get("items") or []
        services = json.loads(services_json).get("items") or []
    except ValueError:
        return None
    for item in ingresses:
        spec = item.get("spec") or {}
        for rule in spec.get("rules") or []:
            host = str(rule.get("host") or "").strip().lower()
            if host and _HOST_RE.match(host) and "*" not in host:
                return f"{'https' if spec.get('tls') else 'http'}://{host}"
    for item in services:
        spec = item.get("spec") or {}
        if spec.get("type") != "LoadBalancer":
            continue
        lb = ((item.get("status") or {}).get("loadBalancer") or {}).get("ingress") or []
        ports = spec.get("ports") or []
        if not lb or not ports:
            continue
        address = str(lb[0].get("hostname") or lb[0].get("ip") or "")
        if not address or not _HOST_RE.match(address.replace(":", "")):
            continue
        port = ports[0].get("port")
        scheme = "https" if port == 443 else "http"
        suffix = "" if port in (80, 443) or not isinstance(port, int) else f":{port}"
        return f"{scheme}://{address}{suffix}"
    return None


async def _teardown_in_session(session: _Session, run_id: uuid.UUID) -> None:
    ns, release = preview_namespace(run_id), preview_release(run_id)
    if await _get_namespace(session, run_id) is None:
        return  # already gone: idempotent
    wait = f"{session.timeout}s"
    uninstall = await session.helm(
        "uninstall", release, "--namespace", ns, "--wait", "--timeout", wait, "--no-hooks",
        check=False,
    )  # fmt: skip
    problem = ""
    if uninstall.returncode != 0 and not _not_found(uninstall):
        problem = scrub(uninstall.stderr or uninstall.stdout, session.kube.secrets)
    deleted = await session.kubectl(
        "delete", "namespace", ns, "--ignore-not-found=true", "--wait=true", f"--timeout={wait}",
        check=False,
    )  # fmt: skip
    if deleted.returncode != 0:
        detail = scrub(deleted.stderr or deleted.stdout, session.kube.secrets)
        raise PreviewError(f"namespace delete failed: {detail} {problem}".strip())


def _deployment(
    run_id: uuid.UUID,
    expires_at: datetime,
    status: Literal["deployed", "failed", "deleted", "simulated"],
    *,
    url: str | None = None,
    sha: str | None = None,
    error: str | None = None,
) -> PreviewDeployment:
    return PreviewDeployment(
        run_id=run_id,
        namespace=preview_namespace(run_id),
        url=url,
        status=status,
        expires_at=expires_at,
        source_sha=sha,
        error=error,
    )


async def deploy_preview(
    ws: Workspace,
    credentials: dict[str, str],
    *,
    options: PreviewOptions | None = None,
    expected_sha: str | None = None,
) -> PreviewDeployment:
    """Deploy the workspace's chart into this run's preview namespace.

    Never raises for an expected failure: the result has status "failed" and a
    safe error. `expected_sha`, when given, must match the workspace HEAD (the
    runner passes the commit the second human approved).
    """
    opts = options or PreviewOptions()
    expires_at = _utcnow() + timedelta(hours=opts.ttl_hours)
    if is_simulated():
        # No network, no cluster, no subprocess, no credential use, no URL.
        return _deployment(ws.run_id, expires_at, "simulated", sha=expected_sha or ws.base_sha)

    sha: str | None = None
    session: _Session | None = None
    work: Path | None = None
    namespace_touched = False
    try:
        _check_options(opts)
        for tool in ("helm", "kubectl"):
            if not cli.tool_available(tool):
                raise PreviewError(f"{tool} is not installed on the engine host")
        session = _Session(credentials)
        sha = await _verified_head(ws, opts, expected_sha)
        work = Path(tempfile.mkdtemp(prefix="asep-stage-"))
        staged = chartmod.stage_chart(ws.path, opts.chart_path, opts.values_file, work)
        problems = chartmod.static_check(staged)
        if problems:
            raise PreviewError("chart rejected: " + "; ".join(problems[:8]))
        rendered = await _render_and_check(work, ws.run_id, staged, opts, expires_at)
        frozen_chart = freeze_checked_manifests(rendered, work / "validated-chart")
        rollback_flag = await _helm_rollback_flag(work)

        await _get_namespace(session, ws.run_id)  # refuses a foreign namespace
        namespace_touched = True
        await session.kubectl(
            "apply", "-f", "-", input_text=_namespace_manifest(ws.run_id, expires_at)
        )
        ns, release = preview_namespace(ws.run_id), preview_release(ws.run_id)
        overlay = work / "preview-overlay.yaml"
        wait = f"{session.timeout}s"
        install = ["upgrade", "--install", release, str(frozen_chart), "--namespace", ns]
        if staged.values_file is not None:
            install += ["--values", str(staged.values_file)]
        install += ["--values", str(overlay), rollback_flag, "--wait", "--timeout", wait]
        install += ["--no-hooks", "--skip-crds", "--history-max", "2"]
        await session.helm(*install)

        installed = await session.helm("get", "manifest", release, "--namespace", ns)
        post = chartmod.check_rendered_manifests(
            installed.stdout, ns, get_preview_settings().allowed_image_registries
        )
        if post:
            raise PreviewError("installed manifests broke policy: " + "; ".join(post[:5]))

        ingress = await session.kubectl("get", "ingress", "-n", ns, "-o", "json")
        services = await session.kubectl("get", "service", "-n", ns, "-o", "json")
        url = discover_url(ingress.stdout, services.stdout)
        log.info("preview.deployed", run_id=str(ws.run_id), namespace=ns, has_url=bool(url))
        return _deployment(ws.run_id, expires_at, "deployed", url=url, sha=sha)
    except PreviewError as exc:
        message = str(exc)
        if session is not None and namespace_touched:
            try:
                await _teardown_in_session(session, ws.run_id)
            except PreviewError:
                message += " (cleanup incomplete; the TTL sweep will remove the namespace)"
        log.warning("preview.failed", run_id=str(ws.run_id), error=message[:300])
        return _deployment(ws.run_id, expires_at, "failed", sha=sha, error=message)
    finally:
        if session is not None:
            session.close()
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ smoke


async def run_cloud_smoke_tests(
    url: str,
    *,
    paths: list[str] | None = None,
    timeout_seconds: int = 30,
) -> SmokeResult:
    """HTTP checks against the preview URL. Simulated mode sends nothing."""
    chosen = paths if paths is not None else PreviewOptions().smoke_paths
    if is_simulated():
        return SmokeResult(
            passed=False,
            checks=[{"path": p, "simulated": True, "ok": None, "status": None} for p in chosen],
            error="simulated: no request was sent, so nothing was verified",
        )
    prefs = get_preview_settings()
    return await smoke.run_smoke(
        url,
        chosen,
        timeout_seconds,
        allow_private=prefs.preview_allow_private_smoke,
        allow_local=prefs.preview_allow_local_cluster,
    )


# --------------------------------------------------------------- teardown


def _require_run_derived(deployment: PreviewDeployment) -> None:
    if deployment.namespace != preview_namespace(deployment.run_id):
        raise PreviewError("refusing to touch a namespace that is not this run's preview")


async def teardown_preview(deployment: PreviewDeployment, credentials: dict[str, str]) -> None:
    """Delete the preview's release and namespace. Safe to call repeatedly."""
    _require_run_derived(deployment)
    if deployment.status in ("simulated", "deleted"):
        return
    if is_simulated():
        raise PreviewError("real preview cleanup is unavailable while LLM_FAKE is enabled")
    for tool in ("helm", "kubectl"):
        if not cli.tool_available(tool):
            raise PreviewError(f"{tool} is not installed on the engine host")
    with _Session(credentials) as session:
        await _teardown_in_session(session, deployment.run_id)
    log.info("preview.deleted", run_id=str(deployment.run_id), namespace=deployment.namespace)


async def teardown_preview_for_run(run_id: uuid.UUID, credentials: dict[str, str]) -> None:
    """Merge-time cleanup hook: only the run id is needed."""
    stub = _deployment(run_id, _utcnow(), "deployed")
    await teardown_preview(stub, credentials)


@dataclass
class SweepResult:
    cleaned: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


async def sweep_expired_previews(
    credentials: dict[str, str], *, now: datetime | None = None
) -> SweepResult:
    """TTL hook: delete every labelled preview namespace past its expiry.

    Reads expiry from the cluster itself, so it works even when the database
    row is gone. Unlabelled or malformed namespaces are never touched.
    """
    result = SweepResult()
    if is_simulated():
        return result
    moment = now or _utcnow()
    with _Session(credentials) as session:
        listing = await session.kubectl(
            "get", "namespaces", "-l", f"{LABEL_MANAGED}={MANAGED_VALUE}", "-o", "json"
        )
        try:
            items = json.loads(listing.stdout).get("items") or []
        except ValueError:
            raise PreviewError("kubectl returned unreadable namespace data") from None
        for item in items:
            meta = item.get("metadata") or {}
            name = str(meta.get("name", ""))
            if not _NAMESPACE_RE.match(name):
                continue
            try:
                expires = datetime.fromisoformat(
                    str((meta.get("annotations") or {}).get(ANNOTATION_EXPIRES, ""))
                )
            except ValueError:
                continue
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires > moment:
                continue
            try:
                await _teardown_in_session(session, uuid.UUID(name.removeprefix(NAMESPACE_PREFIX)))
                result.cleaned.append(name)
            except PreviewError:
                result.failed.append(name)
    return result
