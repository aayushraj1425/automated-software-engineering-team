"""Preview adapter: kubeconfig validation and untrusted-chart checks."""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from engine.deploy import chart as chartmod
from engine.deploy.kubeconfig import sanitize_kubeconfig
from engine.deploy.safety import PreviewError, scrub
from tests.preview_support import CA_DATA, FIXTURE_CHART, TOKEN, kubeconfig_text

# ------------------------------------------------------------- kubeconfig


def test_good_kubeconfig_is_rebuilt_minimal():
    safe = sanitize_kubeconfig(kubeconfig_text())
    doc = yaml.safe_load(safe.text)
    assert doc["current-context"] == "asep-preview"
    assert doc["clusters"][0]["cluster"] == {
        "server": "https://k8s.preview.example.net:6443",
        "certificate-authority-data": CA_DATA,
    }
    assert doc["users"][0]["user"] == {"token": TOKEN}
    assert TOKEN in safe.secrets and CA_DATA in safe.secrets
    assert safe.server_host == "k8s.preview.example.net"


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"user": {"exec": {"command": "/bin/steal", "args": ["x"]}}}, "exec"),
        ({"user": {"auth-provider": {"name": "gcp"}}}, "auth-provider"),
        ({"user": {"tokenFile": "/var/run/secrets/token"}}, "tokenfile"),
        ({"user": {"client-certificate": "/home/u/cert.pem"}}, "client-certificate"),
        ({"user": {"client-key": "/home/u/key.pem"}}, "client-key"),
        ({"user": {"username": "admin", "password": "hunter2-hunter2"}}, "password"),
        ({"user": {"as": "system:admin"}}, "as"),
        ({"cluster": {"certificate-authority": "/etc/ca.pem"}}, "certificate-authority"),
        ({"cluster": {"proxy-url": "http://proxy.evil.test:3128"}}, "proxy-url"),
        ({"cluster": {"insecure-skip-tls-verify": True}}, "insecure-skip-tls-verify"),
    ],
)
def test_forbidden_credential_hooks_are_rejected_without_echoing_values(patch, field):
    with pytest.raises(PreviewError) as err:
        sanitize_kubeconfig(kubeconfig_text(**patch))
    message = str(err.value)
    assert field in message
    for leaked in (TOKEN, "/bin/steal", "hunter2", "evil.test", "/etc/ca.pem", "/home/u"):
        assert leaked not in message


def test_unknown_fields_are_rejected_not_copied():
    with pytest.raises(PreviewError, match="unsupported field"):
        sanitize_kubeconfig(kubeconfig_text(cluster={"extensions": [{"name": "x"}]}))


@pytest.mark.parametrize(
    "server",
    [
        "http://k8s.preview.example.net",
        "https://169.254.169.254",
        "https://metadata.google.internal",
        "https://127.0.0.1:6443",
        "https://localhost:6443",
        "https://user:pw@k8s.preview.example.net",
    ],
)
def test_unsafe_api_servers_are_rejected(server):
    with pytest.raises(PreviewError):
        sanitize_kubeconfig(kubeconfig_text(cluster={"server": server}))


def test_loopback_needs_explicit_opt_in():
    text = kubeconfig_text(cluster={"server": "https://127.0.0.1:6443"})
    assert sanitize_kubeconfig(text, allow_local_cluster=True).server_host == "127.0.0.1"


def test_api_host_allow_list_is_enforced():
    sanitize_kubeconfig(kubeconfig_text(), allowed_api_hosts=["*.example.net"])
    with pytest.raises(PreviewError, match="allowed list"):
        sanitize_kubeconfig(kubeconfig_text(), allowed_api_hosts=["*.other.test"])


@pytest.mark.parametrize(
    "patch",
    [
        {"cluster": {"server": "https://prod-cluster.example.net"}},
        {"context": {"cluster": "preview-cluster"}, "user": {}},
    ],
)
def test_production_looking_clusters_are_refused(patch):
    text = kubeconfig_text(**patch)
    if "context" in patch:
        doc = yaml.safe_load(text)
        doc["current-context"] = "production"
        doc["contexts"][0]["name"] = "production"
        text = yaml.safe_dump(doc)
    with pytest.raises(PreviewError, match="production"):
        sanitize_kubeconfig(text)


def test_malformed_input_never_quotes_the_text():
    for raw in ("", "   ", "token: [unclosed " + TOKEN, "- just\n- a list", "x" * 70_000):
        with pytest.raises(PreviewError) as err:
            sanitize_kubeconfig(raw)
        assert TOKEN not in str(err.value)


def test_user_without_credentials_is_rejected():
    doc = yaml.safe_load(kubeconfig_text())
    doc["users"][0]["user"] = {}
    with pytest.raises(PreviewError, match="token or client certificate"):
        sanitize_kubeconfig(yaml.safe_dump(doc))


def test_scrub_removes_secrets_pem_and_long_tokens():
    pem = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    text = f"failed with {TOKEN} and {pem} and Bearer abc.def and {'A' * 80}"
    cleaned = scrub(text, (TOKEN,))
    assert TOKEN not in cleaned and "PRIVATE KEY" not in cleaned and "A" * 80 not in cleaned
    assert "abc.def" not in cleaned
    # a normal run-derived name is not mistaken for key material
    name = f"asep-preview-{uuid.uuid4().hex}"
    assert name in scrub(f"namespace {name} not found")


# ------------------------------------------------------------------ chart


def stage(tmp_path: Path, chart_dir: Path, **kw):
    root = tmp_path / "ws"
    shutil.copytree(chart_dir, root / "deploy" / "helm", dirs_exist_ok=True)
    return chartmod.stage_chart(
        root, kw.pop("chart_path", "deploy/helm"), kw.pop("values", None), tmp_path / "out"
    )


def test_fixture_chart_passes_static_checks(tmp_path):
    staged = stage(tmp_path, FIXTURE_CHART)
    assert chartmod.static_check(staged) == []
    assert (staged.chart_dir / "templates" / "deployment.yaml").is_file()
    assert staged.chart_dir.parent != FIXTURE_CHART  # checked copy, not the original


@pytest.mark.parametrize("reference", ["http://169.254.169.254/", "file:///etc/secrets"])
def test_schema_cannot_fetch_external_references(tmp_path, reference):
    staged = stage(tmp_path, FIXTURE_CHART)
    (staged.chart_dir / "values.schema.json").write_text(
        json.dumps({"properties": {"image": {"$ref": reference}}}), encoding="utf-8"
    )
    assert any("external schema" in problem for problem in chartmod.static_check(staged))


def test_malformed_rendered_fields_fail_without_an_exception():
    assert chartmod.check_rendered_manifests(
        "apiVersion: batch/v1\nkind: CronJob\nspec:\n  jobTemplate: 7\n", "asep-preview-test"
    )


def test_fixture_values_example_is_accepted(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    staged = chartmod.stage_chart(
        root, "deploy/helm", "deploy/helm/values-preview.yaml", tmp_path / "o"
    )
    assert staged.values_file is not None
    assert chartmod.static_check(staged) == []


@pytest.mark.parametrize("bad", ["../escape", "/etc", "C:\\Windows", "deploy/../../x"])
def test_chart_path_cannot_escape_the_workspace(tmp_path, bad):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    with pytest.raises(PreviewError, match="escapes the workspace"):
        chartmod.stage_chart(root, bad, None, tmp_path / "o")


def test_values_file_cannot_escape_or_be_huge(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    with pytest.raises(PreviewError, match="escapes"):
        chartmod.stage_chart(root, "deploy/helm", "../secrets.yaml", tmp_path / "o")
    (root / "big.yaml").write_text("a: " + "x" * 300_000)
    with pytest.raises(PreviewError, match="too large"):
        chartmod.stage_chart(root, "deploy/helm", "big.yaml", tmp_path / "o2")


def test_missing_chart_is_reported(tmp_path):
    (tmp_path / "ws").mkdir()
    with pytest.raises(PreviewError, match="no Helm chart"):
        chartmod.stage_chart(tmp_path / "ws", "deploy/helm", None, tmp_path / "o")


def test_symlinks_in_a_chart_are_rejected(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    try:
        os.symlink(secret, root / "deploy" / "helm" / "templates" / "leak.yaml")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(PreviewError, match="link"):
        chartmod.stage_chart(root, "deploy/helm", None, tmp_path / "o")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_junctions_in_a_chart_are_rejected(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.yaml").write_text("a: 1")
    junction = root / "deploy" / "helm" / "templates" / "linked"
    made = subprocess.run(  # noqa: S603
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction here")
    with pytest.raises(PreviewError, match="link"):
        chartmod.stage_chart(root, "deploy/helm", None, tmp_path / "o")


def test_oversize_chart_is_rejected(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    for index in range(chartmod.MAX_CHART_FILES + 1):
        (root / "deploy" / "helm" / "templates" / f"f{index}.yaml").write_text("a: 1")
    with pytest.raises(PreviewError, match="too large"):
        chartmod.stage_chart(root, "deploy/helm", None, tmp_path / "o")


def add(tmp_path: Path, rel: str, text: str | bytes):
    root = tmp_path / "ws" / "deploy" / "helm"
    shutil.copytree(FIXTURE_CHART, root, dirs_exist_ok=True)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text)


@pytest.mark.parametrize(
    ("rel", "text", "needle"),
    [
        ("crds/crd.yaml", "kind: CustomResourceDefinition", "crds/"),
        ("templates/leak.yaml", 'x: {{ lookup "v1" "Secret" "kube-system" "s" }}', "lookup"),
        ("templates/dns.yaml", 'x: {{ getHostByName "internal.corp" }}', "getHostByName"),
        (
            "templates/cap.yaml",
            '{{ if .Capabilities.APIVersions.Has "x/v1" }}a: 1{{ end }}',
            ".Capabilities",
        ),
        ("templates/up.yaml", "{{ if .Release.IsUpgrade }}a: 1{{ end }}", "IsUpgrade"),
        ("values.yaml", "a: &x [1]\nb: *x\n", "aliases"),
        ("charts/dep.tgz", b"\x1f\x8b\x08\x00", "unpack"),
    ],
)
def test_static_check_rejects_unsafe_chart_content(tmp_path, rel, text, needle):
    add(tmp_path, rel, text)
    staged = chartmod.stage_chart(tmp_path / "ws", "deploy/helm", None, tmp_path / "o")
    problems = chartmod.static_check(staged)
    assert any(needle in p for p in problems), problems


def test_remote_and_file_dependencies_are_rejected(tmp_path):
    add(
        tmp_path,
        "Chart.yaml",
        (FIXTURE_CHART / "Chart.yaml").read_text()
        + """
dependencies:
  - name: evil
    version: 1.0.0
    repository: file:///etc
""",
    )
    staged = chartmod.stage_chart(tmp_path / "ws", "deploy/helm", None, tmp_path / "o")
    assert any("dependencies" in p for p in chartmod.static_check(staged))


def test_user_values_with_template_functions_are_rejected(tmp_path):
    root = tmp_path / "ws"
    shutil.copytree(FIXTURE_CHART, root / "deploy" / "helm")
    (root / "v.yaml").write_text('note: \'{{ lookup "v1" "Secret" "ns" "n" }}\'\n')
    staged = chartmod.stage_chart(root, "deploy/helm", "v.yaml", tmp_path / "o")
    assert any("lookup" in p for p in chartmod.static_check(staged))


# ------------------------------------------------- rendered manifest policy

NS = "asep-preview-" + "a" * 32


def doc(kind: str, api: str = "v1", meta: str = "", spec: str = "", top: str = "") -> str:
    return f"apiVersion: {api}\nkind: {kind}\nmetadata:\n  name: t\n{meta}{top}spec:\n{spec or '  x: 1'}\n"  # noqa: E501


def workload(container: str = "", pod: str = "") -> str:
    return (
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: t\nspec:\n  template:\n"
        f"    spec:\n{pod}      containers:\n        - name: c\n          image: nginx:1\n{container}"  # noqa: E501
    )


GOOD = workload() + "---\n" + doc("Service", spec="  type: ClusterIP")


def test_clean_manifests_pass():
    assert chartmod.check_rendered_manifests(GOOD, NS) == []
    assert (
        chartmod.check_rendered_manifests(
            GOOD.replace("name: t\nspec", f"name: t\n  namespace: {NS}\nspec", 1), NS
        )
        == []
    )


@pytest.mark.parametrize(
    ("manifest", "needle"),
    [
        (doc("ClusterRole", "rbac.authorization.k8s.io/v1"), "not allowed"),
        (doc("ClusterRoleBinding", "rbac.authorization.k8s.io/v1"), "not allowed"),
        (doc("Namespace"), "not allowed"),
        (doc("Role", "rbac.authorization.k8s.io/v1"), "not allowed"),
        (doc("CustomResourceDefinition", "apiextensions.k8s.io/v1"), "not allowed"),
        (doc("MutatingWebhookConfiguration", "admissionregistration.k8s.io/v1"), "not allowed"),
        (doc("PersistentVolume"), "not allowed"),
        (doc("Ingress", "example.io/v1"), "not allowed"),
        (workload(pod="      hostNetwork: true\n"), "hostNetwork"),
        (workload(pod="      hostPID: true\n"), "hostPID"),
        (
            workload(pod="      volumes:\n        - name: v\n          hostPath: {path: /}\n"),
            "hostPath",
        ),
        (
            workload(container="          securityContext:\n            privileged: true\n"),
            "privileged",
        ),
        (
            workload(
                container="          securityContext:\n            capabilities:\n              add: [SYS_ADMIN]\n"  # noqa: E501
            ),
            "capabilities",
        ),
        (
            workload(
                container="          ports:\n            - containerPort: 80\n              hostPort: 80\n"  # noqa: E501
            ),
            "hostPort",
        ),
        (doc("Service", spec="  type: NodePort"), "service type"),
        (
            doc("Service", spec="  type: ExternalName\n  externalName: internal.corp"),
            "service type",
        ),
        (doc("Service", spec="  externalIPs: [10.0.0.1]"), "externalIPs"),
        (doc("ConfigMap", meta="  annotations:\n    helm.sh/hook: pre-install\n"), "hooks"),
        (doc("ConfigMap", meta="  namespace: kube-system\n"), "different namespace"),
        (doc("Secret", top="type: kubernetes.io/service-account-token\n"), "service-account-token"),
    ],
)
def test_rendered_manifest_policy_rejects(manifest, needle):
    problems = chartmod.check_rendered_manifests(manifest, NS)
    assert problems and any(needle in p for p in problems), problems


def test_image_registry_allow_list():
    assert chartmod.check_rendered_manifests(GOOD, NS, ["docker.io"]) == []
    private = GOOD.replace("nginx:1", "registry.corp.test/team/app:1")
    assert chartmod.check_rendered_manifests(private, NS, ["registry.corp.test"]) == []
    assert any(
        "registry" in p for p in chartmod.check_rendered_manifests(private, NS, ["docker.io"])
    )


def test_empty_aliased_or_huge_renders_are_rejected():
    assert chartmod.check_rendered_manifests("", NS)
    assert chartmod.check_rendered_manifests("a: &x 1\nb: *x\n", NS)
    many = "---\n".join(doc("ConfigMap") for _ in range(chartmod.MAX_RENDERED_DOCS + 1))
    assert any("more than" in p for p in chartmod.check_rendered_manifests(many, NS))
