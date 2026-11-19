"""Untrusted-chart checks. The repository is attacker-influenced input.

Three layers, all before any privileged Helm or kubectl call:
1. stage_chart: copy the chart into a private folder (no symlinks, size limits)
   so what we check is exactly what Helm later runs.
2. static_check: files and template text that can make the install differ from
   the check, or reach outside the chart.
3. check_rendered_manifests: policy over the output of `helm template`.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from engine.deploy.frozen import schema_reference_problems
from engine.deploy.safety import PreviewError
from engine.workspace.jail import JailViolation, resolve_inside

MAX_CHART_FILES = 500
MAX_CHART_BYTES = 5_000_000
MAX_VALUES_BYTES = 256_000
MAX_RENDERED_BYTES = 5_000_000
MAX_RENDERED_DOCS = 60

# Template functions and objects whose result depends on the live cluster or
# the network, so the installed manifests could differ from the ones we checked.
_FORBIDDEN_TEMPLATE = re.compile(
    r"\blookup\b|\bgetHostByName\b|\.Capabilities\b|\.Release\.(IsUpgrade|IsInstall|Revision)\b"
)
_TEXT_SCAN_SKIP = (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")

# kind -> apiVersions we accept. Anything else (cluster scoped kinds, RBAC,
# webhooks, CRDs, custom resources) is rejected by omission.
_ALLOWED_KINDS: dict[str, frozenset[str]] = {
    "Deployment": frozenset({"apps/v1"}),
    "StatefulSet": frozenset({"apps/v1"}),
    "Job": frozenset({"batch/v1"}),
    "CronJob": frozenset({"batch/v1"}),
    "Service": frozenset({"v1"}),
    "ConfigMap": frozenset({"v1"}),
    "Secret": frozenset({"v1"}),
    "ServiceAccount": frozenset({"v1"}),
    "PersistentVolumeClaim": frozenset({"v1"}),
    "Ingress": frozenset({"networking.k8s.io/v1"}),
    "NetworkPolicy": frozenset({"networking.k8s.io/v1"}),
    "HorizontalPodAutoscaler": frozenset({"autoscaling/v2", "autoscaling/v1"}),
    "PodDisruptionBudget": frozenset({"policy/v1"}),
}
_SAFE_CAPABILITIES = frozenset({"NET_BIND_SERVICE"})
_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-:@]{0,254}$")


@dataclass(frozen=True)
class StagedChart:
    chart_dir: Path
    values_file: Path | None


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _reject_aliases(text: str, what: str) -> Any:
    """Parse YAML but refuse aliases/anchors: they allow exponential expansion."""
    try:
        for event in yaml.parse(text):
            if isinstance(event, yaml.AliasEvent):
                raise PreviewError(f"{what}: YAML aliases are not allowed")
        return yaml.safe_load(text)
    except yaml.YAMLError:
        raise PreviewError(f"{what} is not valid YAML") from None


def stage_chart(
    workspace_root: Path, chart_path: str, values_file: str | None, dest: Path
) -> StagedChart:
    """Copy the chart (and optional values file) out of the workspace, checking as we go."""
    try:
        src = resolve_inside(workspace_root, chart_path)
        values_src = resolve_inside(workspace_root, values_file) if values_file else None
    except JailViolation:
        raise PreviewError("chart_path or values_file escapes the workspace") from None
    if not src.is_dir() or not (src / "Chart.yaml").is_file():
        raise PreviewError(f"no Helm chart (Chart.yaml) found at {chart_path!r}")

    chart_dir = dest / "chart"
    files = 0
    total = 0
    for current, dirs, names in os.walk(src, followlinks=False):
        here = Path(current)
        for name in list(dirs):
            if _is_link(here / name):
                raise PreviewError("the chart contains a symlink or junction, which is not allowed")
            if name == ".git":
                dirs.remove(name)
        rel = here.relative_to(src)
        (chart_dir / rel).mkdir(parents=True, exist_ok=True)
        for name in names:
            item = here / name
            if _is_link(item) or not item.is_file():
                raise PreviewError(
                    "the chart contains a link or special file, which is not allowed"
                )
            files += 1
            total += item.stat().st_size
            if files > MAX_CHART_FILES or total > MAX_CHART_BYTES:
                raise PreviewError("the chart is too large to deploy as a preview")
            shutil.copyfile(item, chart_dir / rel / name)

    staged_values: Path | None = None
    if values_src is not None:
        if not values_src.is_file() or _is_link(values_src):
            raise PreviewError(f"values file not found: {values_file!r}")
        if values_src.stat().st_size > MAX_VALUES_BYTES:
            raise PreviewError("the values file is too large")
        staged_values = dest / "user-values.yaml"
        shutil.copyfile(values_src, staged_values)
    return StagedChart(chart_dir=chart_dir, values_file=staged_values)


def static_check(staged: StagedChart) -> list[str]:
    """Return problems found in the staged files. Empty means acceptable."""
    problems: list[str] = []
    root = staged.chart_dir

    chart_meta: Any = None
    try:
        chart_meta = _reject_aliases(
            (root / "Chart.yaml").read_text(encoding="utf-8", errors="replace"), "Chart.yaml"
        )
    except PreviewError as exc:
        problems.append(str(exc))
    if isinstance(chart_meta, dict):
        if chart_meta.get("apiVersion") != "v2":
            problems.append("Chart.yaml: apiVersion must be v2")
        dependencies = chart_meta.get("dependencies") or []
        if not isinstance(dependencies, list):
            problems.append("Chart.yaml: dependencies must be a list")
            dependencies = []
        for dep in dependencies:
            repo = str(dep.get("repository", "")) if isinstance(dep, dict) else ""
            if repo:
                problems.append(
                    "Chart.yaml: remote or file chart dependencies are not allowed; "
                    "vendor them under charts/ and leave repository empty"
                )
    elif chart_meta is not None or not problems:
        problems.append("Chart.yaml must be a mapping")

    for child in root.iterdir():
        if child.name.lower() == "crds":
            problems.append("crds/ is not allowed: CRDs are cluster scoped")
    subcharts = root / "charts"
    if subcharts.is_dir():
        for child in subcharts.iterdir():
            if child.is_file():
                problems.append(
                    f"charts/{child.name}: packaged subcharts cannot be inspected; unpack them"
                )

    scan_targets: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() not in _TEXT_SCAN_SKIP:
            scan_targets.append(path)
    if staged.values_file is not None:
        scan_targets.append(staged.values_file)
    for path in scan_targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "values.schema.json":
            try:
                schema = json.loads(text)
                if not isinstance(schema, (dict, bool)):
                    problems.append("values.schema.json: schema must be an object or boolean")
                else:
                    problems.extend(schema_reference_problems(schema))
            except (ValueError, RecursionError):
                problems.append("values.schema.json is not valid JSON")
        match = _FORBIDDEN_TEMPLATE.search(text)
        if match:
            shown = path.name
            problems.append(
                f"{shown}: '{match.group(0).strip()}' makes the install depend on the "
                "live cluster and is not allowed in preview charts"
            )
        if path.name in ("values.yaml", "values.yml") or path == staged.values_file:
            try:
                _reject_aliases(text, path.name)
            except PreviewError as exc:
                problems.append(str(exc))
    return problems


def _pod_spec(doc: dict) -> dict | None:
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind in ("Deployment", "StatefulSet", "Job"):
        template = (spec.get("template") or {}) if isinstance(spec, dict) else {}
    elif kind == "CronJob":
        job = (spec.get("jobTemplate") or {}).get("spec") or {}
        template = job.get("template") or {}
    else:
        return None
    pod = template.get("spec") if isinstance(template, dict) else None
    return pod if isinstance(pod, dict) else {}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _registry_of(image: str) -> str:
    first, _, rest = image.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        return first.lower()
    return "docker.io"


def _check_container(
    label: str, container: Any, allowed_registries: list[str], problems: list[str]
) -> None:
    if not isinstance(container, dict):
        return
    image = container.get("image")
    if not isinstance(image, str) or not _IMAGE_REF.match(image):
        problems.append(f"{label}: container image is missing or malformed")
    elif allowed_registries and _registry_of(image) not in {r.lower() for r in allowed_registries}:
        problems.append(f"{label}: image registry '{_registry_of(image)}' is not allowed")
    sc = container.get("securityContext") or {}
    if isinstance(sc, dict):
        if sc.get("privileged"):
            problems.append(f"{label}: privileged containers are not allowed")
        if sc.get("allowPrivilegeEscalation"):
            problems.append(f"{label}: allowPrivilegeEscalation is not allowed")
        if sc.get("procMount") not in (None, "Default"):
            problems.append(f"{label}: procMount must be Default")
        added = set((sc.get("capabilities") or {}).get("add") or [])
        if added - _SAFE_CAPABILITIES:
            problems.append(f"{label}: added Linux capabilities are not allowed")
    for port in container.get("ports") or []:
        if isinstance(port, dict) and port.get("hostPort"):
            problems.append(f"{label}: hostPort is not allowed")


def _check_pod(label: str, pod: dict, allowed_registries: list[str], problems: list[str]) -> None:
    for flag in ("hostNetwork", "hostPID", "hostIPC"):
        if pod.get(flag):
            problems.append(f"{label}: {flag} is not allowed")
    for volume in pod.get("volumes") or []:
        if isinstance(volume, dict) and "hostPath" in volume:
            problems.append(f"{label}: hostPath volumes are not allowed")
    sc = pod.get("securityContext") or {}
    if isinstance(sc, dict) and sc.get("sysctls"):
        problems.append(f"{label}: sysctls are not allowed")
    for group in ("containers", "initContainers"):
        for container in pod.get(group) or []:
            _check_container(label, container, allowed_registries, problems)


def check_rendered_manifests(
    rendered: str, namespace: str, allowed_registries: list[str] | None = None
) -> list[str]:
    try:
        return _check_rendered_manifests(rendered, namespace, allowed_registries)
    except (TypeError, AttributeError, ValueError, RecursionError):
        return ["rendered manifests contain malformed resource fields"]


def _check_rendered_manifests(
    rendered: str, namespace: str, allowed_registries: list[str] | None = None
) -> list[str]:
    """Policy for `helm template` output. Returns problems; empty means allowed."""
    if len(rendered.encode("utf-8")) > MAX_RENDERED_BYTES:
        return ["rendered manifests are too large"]
    try:
        for event in yaml.parse(rendered):
            if isinstance(event, yaml.AliasEvent):
                return ["rendered manifests use YAML aliases, which are not allowed"]
        docs = [d for d in yaml.safe_load_all(rendered) if d is not None]
    except yaml.YAMLError:
        return ["rendered manifests are not valid YAML"]
    if not docs:
        return ["the chart rendered no resources"]
    if len(docs) > MAX_RENDERED_DOCS:
        return [f"the chart renders more than {MAX_RENDERED_DOCS} resources"]

    problems: list[str] = []
    registries = allowed_registries or []
    for doc in docs:
        if not isinstance(doc, dict):
            problems.append("a rendered document is not a mapping")
            continue
        kind, api = doc.get("kind"), doc.get("apiVersion")
        meta = _dict(doc.get("metadata"))
        label = f"{kind}/{meta.get('name', '?')}"
        if kind not in _ALLOWED_KINDS or api not in _ALLOWED_KINDS[str(kind)]:
            problems.append(f"{label}: kind {kind!r} ({api}) is not allowed in preview charts")
            continue
        annotations = _dict(meta.get("annotations"))
        if any(str(key).startswith("helm.sh/hook") for key in annotations):
            problems.append(f"{label}: Helm hooks are not allowed")
        if meta.get("namespace") not in (None, "", namespace):
            problems.append(f"{label}: it targets a different namespace")
        pod = _pod_spec(doc)
        if pod is not None:
            _check_pod(label, pod, registries, problems)
        spec = _dict(doc.get("spec"))
        if kind == "Service":
            if spec.get("type") not in (None, "ClusterIP", "LoadBalancer"):
                problems.append(f"{label}: service type {spec.get('type')!r} is not allowed")
            if spec.get("externalIPs") or spec.get("loadBalancerIP"):
                problems.append(f"{label}: externalIPs and loadBalancerIP are not allowed")
        if kind == "Secret" and doc.get("type") == "kubernetes.io/service-account-token":
            problems.append(f"{label}: service-account-token secrets are not allowed")
    return problems
