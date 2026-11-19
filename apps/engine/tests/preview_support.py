"""Shared helpers for the preview adapter tests: a scripted helm/kubectl cluster."""

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from engine.deploy import cli, preview
from engine.workspace.manager import Workspace

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_CHART = REPO_ROOT / "infra" / "helm" / "asep-preview-fixture"

TOKEN = "tok-secret-value-1234567890-ABCDEFGH"
CA_DATA = "Q0FfREFUQV9GT1JfVEVTVF9PTkxZ"

GOOD_KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "current-context": "preview-ctx",
    "clusters": [
        {
            "name": "preview-cluster",
            "cluster": {
                "server": "https://k8s.preview.example.net:6443",
                "certificate-authority-data": CA_DATA,
            },
        }
    ],
    "users": [{"name": "preview-user", "user": {"token": TOKEN}}],
    "contexts": [
        {"name": "preview-ctx", "context": {"cluster": "preview-cluster", "user": "preview-user"}}
    ],
}


def kubeconfig_text(**patch) -> str:
    """The good kubeconfig, deep-copied and tweaked: patch keys are 'cluster'/'user'/'context'."""
    doc = json.loads(json.dumps(GOOD_KUBECONFIG))
    doc["clusters"][0]["cluster"].update(patch.get("cluster", {}))
    doc["users"][0]["user"].update(patch.get("user", {}))
    doc["contexts"][0]["context"].update(patch.get("context", {}))
    for key in patch.get("drop_cluster", []):
        doc["clusters"][0]["cluster"].pop(key, None)
    return yaml.safe_dump(doc)


def rendered_for(run_id: uuid.UUID, namespace: str | None = None, extra: str = "") -> str:
    """What `helm template` prints for the fixture chart (hand-written, one ingress)."""
    name = f"{preview.preview_release(run_id)}-web"
    ns_line = f"  namespace: {namespace}\n" if namespace else ""
    return f"""---
apiVersion: v1
kind: Service
metadata:
  name: {name}
{ns_line}spec:
  type: ClusterIP
  ports:
    - port: 80
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: web
          image: nginxinc/nginx-unprivileged:1.27-alpine
          securityContext:
            allowPrivilegeEscalation: false
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {name}
spec:
  tls:
    - hosts: ["preview.example.com"]
  rules:
    - host: preview.example.com
{extra}"""


def make_repo(tmp_path: Path, *, chart: bool = True) -> Workspace:
    """A committed git repo whose deploy/helm is the fixture chart."""
    path = tmp_path / "repo"
    path.mkdir()
    if chart:
        shutil.copytree(FIXTURE_CHART, path / "deploy" / "helm")
    else:
        (path / "README.md").write_text("x")

    def git(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True)  # noqa: S603, S607
        return proc.stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return Workspace(
        run_id=uuid.uuid4(), path=path, branch="asep/run-test", base_sha=git("rev-parse", "HEAD")
    )


@dataclass
class Call:
    argv: list[str]
    env: dict[str, str]
    input_text: str | None
    kubeconfig: str | None  # content of the KUBECONFIG file at call time
    values: dict[str, dict] = field(default_factory=dict)  # --values file name -> parsed


@dataclass
class FakeCluster:
    """Scripted helm/kubectl. Records every call, including what files held."""

    run_id: uuid.UUID
    rendered: str = ""
    installed_manifest: str | None = None
    namespace_exists: bool = False
    namespace_labels: dict[str, str] | None = None
    fail: dict[str, str] = field(default_factory=dict)  # "helm upgrade" -> stderr
    ingress: dict = field(default_factory=lambda: {"items": []})
    services: dict = field(default_factory=lambda: {"items": []})
    namespaces: list[dict] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    helm_help: str = "--atomic"

    def __post_init__(self) -> None:
        if not self.rendered:
            self.rendered = rendered_for(self.run_id)
        if self.namespace_labels is None:
            self.namespace_labels = {
                preview.LABEL_MANAGED: preview.MANAGED_VALUE,
                preview.LABEL_RUN: self.run_id.hex,
            }

    def commands(self) -> list[str]:
        """'helm upgrade', 'kubectl get', ... one entry per call."""
        out = []
        for call in self.calls:
            args = [a for a in call.argv[1:] if not a.startswith("--request-timeout")]
            key = f"{call.argv[0]} {args[0]}"
            if call.argv[0] == "kubectl" and args[0] == "get":
                key += f" {args[1]}"
            out.append(key)
        return out

    async def run_cli(self, argv, *, env, timeout, cwd, input_text=None):
        if argv == ["helm", "upgrade", "--help"]:
            assert "KUBECONFIG" not in env
            return cli.CliResult(0, self.helm_help, "")
        kube = env.get("KUBECONFIG")
        values: dict[str, dict] = {}
        for index, arg in enumerate(argv):
            if arg == "--values":
                values[Path(argv[index + 1]).name] = yaml.safe_load(
                    Path(argv[index + 1]).read_text(encoding="utf-8")
                )
        self.calls.append(
            Call(
                argv=list(argv),
                env=dict(env),
                input_text=input_text,
                kubeconfig=Path(kube).read_text(encoding="utf-8") if kube else None,
                values=values,
            )
        )
        stripped = [a for a in argv if not a.startswith("--request-timeout")]
        keys = {" ".join(stripped[:3]), " ".join(stripped[:2])}
        for prefix, stderr in self.fail.items():
            if prefix in keys:
                return cli.CliResult(1, "", stderr)
        return self._respond(stripped, input_text)

    def _respond(self, argv, input_text):
        ok = cli.CliResult
        tool, sub = argv[0], argv[1]
        if tool == "helm":
            if sub == "template":
                return ok(0, self.rendered, "")
            if sub == "get":
                return ok(0, self.installed_manifest or self.rendered, "")
            if sub == "uninstall":
                return ok(0, "release uninstalled", "")
            return ok(0, "STATUS: deployed", "")
        if sub == "get" and argv[2] == "namespace":
            if not self.namespace_exists:
                return ok(1, "", 'Error from server (NotFound): namespaces "x" not found')
            body = {"metadata": {"name": argv[3], "labels": self.namespace_labels}}
            return ok(0, json.dumps(body), "")
        if sub == "get" and argv[2] == "namespaces":
            return ok(0, json.dumps({"items": self.namespaces}), "")
        if sub == "get" and argv[2] == "ingress":
            return ok(0, json.dumps(self.ingress), "")
        if sub == "get" and argv[2] == "service":
            return ok(0, json.dumps(self.services), "")
        if sub == "apply":
            self.namespace_exists = True
            return ok(0, "namespace/x created", "")
        if sub == "delete":
            self.namespace_exists = False
            return ok(0, "namespace deleted", "")
        raise AssertionError(f"unscripted command: {argv}")


def install_fake(monkeypatch, cluster: FakeCluster, *, tools: bool = True) -> FakeCluster:
    """Route the adapter through `cluster` and turn simulated mode off."""
    monkeypatch.setattr(cli, "run_cli", cluster.run_cli)
    monkeypatch.setattr(cli, "tool_available", lambda tool: tools)
    monkeypatch.setattr(preview, "is_simulated", lambda: False)
    return cluster
