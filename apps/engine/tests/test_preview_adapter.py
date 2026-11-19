"""Preview adapter: deploy, teardown and sweep against a scripted helm/kubectl."""

import base64
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from engine.deploy import cli, preview
from engine.deploy.contracts import PreviewDeployment, PreviewOptions
from engine.deploy.safety import PreviewError
from tests.preview_support import (
    TOKEN,
    FakeCluster,
    install_fake,
    kubeconfig_text,
    make_repo,
    rendered_for,
)

CREDS = {"kubeconfig": kubeconfig_text()}
INGRESS = {
    "items": [{"spec": {"tls": [{}], "rules": [{"host": "preview.example.com"}]}}],
}


def fixture(tmp_path, monkeypatch, **cluster_kw):
    ws = make_repo(tmp_path)
    cluster_kw.setdefault("ingress", INGRESS)
    cluster = install_fake(monkeypatch, FakeCluster(run_id=ws.run_id, **cluster_kw))
    return ws, cluster


def deployed(
    run_id: uuid.UUID,
    status: Literal["deployed", "failed", "deleted", "simulated"] = "deployed",
    hours=24,
) -> PreviewDeployment:
    return PreviewDeployment(
        run_id=run_id,
        namespace=preview.preview_namespace(run_id),
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
    )


# ------------------------------------------------------------------ names


def test_names_are_derived_from_the_run_only():
    run_id = uuid.UUID(int=0xABC)
    assert preview.preview_namespace(run_id) == f"asep-preview-{run_id.hex}"
    assert preview.preview_release(run_id) == f"preview-{run_id.hex}"
    assert (
        len(preview.preview_namespace(run_id)) <= 63 and len(preview.preview_release(run_id)) <= 53
    )


# ------------------------------------------------------------- simulation


async def test_simulated_mode_touches_nothing(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)

    async def forbidden(*a, **k):
        raise AssertionError("simulated mode must not start a process")

    monkeypatch.setattr(cli, "run_cli", forbidden)
    monkeypatch.setattr(preview, "is_simulated", lambda: True)
    result = await preview.deploy_preview(ws, {})  # credentials are not even read
    assert result.status == "simulated" and result.url is None and result.smoke is None
    assert result.namespace == preview.preview_namespace(ws.run_id)
    assert result.expires_at > datetime.now(UTC)
    await preview.teardown_preview(result, {})  # no-op, no process
    assert (await preview.sweep_expired_previews({})).cleaned == []


async def test_default_test_environment_is_simulated(tmp_path):
    # conftest sets LLM_FAKE=1, so without opt-out nothing real can happen.
    assert preview.is_simulated()
    result = await preview.deploy_preview(make_repo(tmp_path), {"kubeconfig": "ignored"})
    assert result.status == "simulated" and result.url is None


# ---------------------------------------------------------------- deploy


@pytest.mark.parametrize("rollback", ["--atomic", "--rollback-on-failure"])
async def test_install_only_evaluates_the_trusted_frozen_chart(tmp_path, monkeypatch, rollback):
    ws, cluster = fixture(tmp_path, monkeypatch, helm_help=rollback)
    original = cluster.run_cli
    captured = []

    async def inspect(argv, **kwargs):
        if argv[:3] == ["helm", "upgrade", "--install"]:
            chart = Path(argv[4])
            assert chart.name == "validated-chart"
            template = (chart / "templates/resources.yaml").read_text(encoding="utf-8")
            match = re.fullmatch(r'\{\{ "([A-Za-z0-9+/=]+)" \| b64dec \}\}\n', template)
            assert match is not None
            captured.append(base64.b64decode(match[1]).decode("utf-8"))
            assert rollback in argv
        return await original(argv, **kwargs)

    monkeypatch.setattr(cli, "run_cli", inspect)
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "deployed", result.error
    assert captured == [cluster.rendered]


async def test_unknown_helm_rollback_support_refuses_before_cluster_writes(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, helm_help="unsupported client")
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "rollback" in (result.error or "")
    assert cluster.commands() == ["helm template"]


async def test_fake_mode_cannot_claim_a_real_preview_was_deleted(monkeypatch):
    monkeypatch.setattr(preview, "is_simulated", lambda: True)
    with pytest.raises(PreviewError, match="real preview cleanup"):
        await preview.teardown_preview(deployed(uuid.uuid4()), {})


async def test_deploy_runs_helm_and_kubectl_in_order(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    result = await preview.deploy_preview(ws, CREDS)
    ns, release = preview.preview_namespace(ws.run_id), preview.preview_release(ws.run_id)

    assert result.status == "deployed" and result.error is None
    assert result.url == "https://preview.example.com"
    assert result.namespace == ns and result.source_sha == ws.base_sha
    assert result.smoke is None  # smoke tests are a separate step
    assert (result.expires_at - datetime.now(UTC)) > timedelta(hours=23)
    assert cluster.commands() == [
        "helm template",
        "kubectl get namespace",
        "kubectl apply",
        "helm upgrade",
        "helm get",
        "kubectl get ingress",
        "kubectl get service",
    ]

    upgrade = next(c for c in cluster.calls if c.argv[:2] == ["helm", "upgrade"])
    argv = upgrade.argv
    assert argv[argv.index("--install") + 1] == release
    assert argv[argv.index("--namespace") + 1] == ns
    for flag in ("--atomic", "--wait", "--no-hooks", "--skip-crds"):
        assert flag in argv
    assert all(not a.startswith("--set") for a in argv)  # repo values only via checked files
    assert argv[-1] != "--post-renderer"

    template = cluster.calls[0]
    assert (
        template.kubeconfig is None and "KUBECONFIG" not in template.env
    )  # render is credential-free
    overlay = template.values["preview-overlay.yaml"]["preview"]
    assert (
        overlay["namespace"] == ns
        and overlay["release"] == release
        and overlay["runId"] == ws.run_id.hex
    )

    applied = cluster.calls[2].input_text or ""
    assert f"asep.io/preview-run-id: {ws.run_id.hex}" in applied
    assert "asep.io/expires-at" in applied and "ResourceQuota" in applied


async def test_credentials_stay_inside_the_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_SERVICE_SECRET", "engine-service-secret-should-not-leak")
    ws, cluster = fixture(tmp_path, monkeypatch)
    await preview.deploy_preview(ws, CREDS)
    privileged = [c for c in cluster.calls if c.kubeconfig is not None]
    assert privileged
    for call in cluster.calls:
        assert TOKEN not in " ".join(call.argv)
        assert "engine-service-secret-should-not-leak" not in " ".join(call.env.values())
        assert "DATABASE_URL" not in call.env
    for call in privileged:
        # a rebuilt, minimal kubeconfig: no exec, no file references
        assert "exec" not in (call.kubeconfig or "") and "client-key:" not in (
            call.kubeconfig or ""
        )
        assert Path(call.env["KUBECONFIG"]).parent == Path(call.env["HOME"]).parents[1]
        assert not Path(call.env["KUBECONFIG"]).exists()  # temp folder removed afterwards


async def test_image_option_reaches_the_overlay_values(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    options = PreviewOptions(image="registry.example.com/team/app:abc123", ttl_hours=2)
    result = await preview.deploy_preview(ws, CREDS, options=options)
    assert result.status == "deployed"
    upgrade = next(c for c in cluster.calls if c.argv[:2] == ["helm", "upgrade"])
    assert upgrade.values["preview-overlay.yaml"]["image"] == "registry.example.com/team/app:abc123"
    assert timedelta(hours=1) < result.expires_at - datetime.now(UTC) <= timedelta(hours=2)


@pytest.mark.parametrize("image", ["--malicious", "a b", "app:1\n--set x=y", "reg//app"])
async def test_bad_image_references_fail_before_any_command(tmp_path, monkeypatch, image):
    ws, cluster = fixture(tmp_path, monkeypatch)
    result = await preview.deploy_preview(ws, CREDS, options=PreviewOptions(image=image))
    assert result.status == "failed" and "image" in (result.error or "") and cluster.calls == []


async def test_values_file_is_checked_and_used(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    result = await preview.deploy_preview(
        ws, CREDS, options=PreviewOptions(values_file="deploy/helm/values-preview.yaml")
    )
    assert result.status == "deployed"
    template = cluster.calls[0]
    assert template.values["user-values.yaml"]["ingress"]["host"] == "preview.example.com"
    # overlay comes last, so the repo cannot override run identity
    assert [Path(a).name for a in template.argv if a.endswith(".yaml")][
        -1
    ] == "preview-overlay.yaml"


async def test_expected_sha_must_match_head(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    wrong = await preview.deploy_preview(ws, CREDS, expected_sha="0" * 40)
    assert wrong.status == "failed" and "approved commit" in (wrong.error or "")
    assert cluster.calls == []
    short = await preview.deploy_preview(ws, CREDS, expected_sha=ws.base_sha[:12])
    assert short.status == "deployed" and short.source_sha == ws.base_sha
    too_short = await preview.deploy_preview(ws, CREDS, expected_sha=ws.base_sha[:3])
    assert too_short.status == "failed"


async def test_uncommitted_changes_are_refused(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    (ws.path / "deploy" / "helm" / "values.yaml").write_text("image: evil\n")
    tracked = await preview.deploy_preview(ws, CREDS)
    assert tracked.status == "failed" and "uncommitted" in (tracked.error or "")
    assert cluster.calls == []


async def test_untracked_chart_files_are_refused(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch)
    (ws.path / "deploy" / "helm" / "templates" / "extra.yaml").write_text("a: 1\n")
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "uncommitted" in (result.error or "")
    assert cluster.calls == []


# --------------------------------------------------- refusals before cluster


async def test_missing_binaries_fail_honestly_not_simulated(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)
    install_fake(monkeypatch, FakeCluster(run_id=ws.run_id), tools=False)
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "not installed" in (result.error or "")
    assert result.url is None


@pytest.mark.parametrize(
    "creds",
    [
        {},
        {"kubeconfig": ""},
        {"kubeconfig": kubeconfig_text(user={"exec": {"command": "/bin/steal"}})},
        {"kubeconfig": kubeconfig_text(cluster={"server": "http://k8s.example.net"})},
    ],
)
async def test_bad_credentials_fail_before_any_command(tmp_path, monkeypatch, creds):
    ws, cluster = fixture(tmp_path, monkeypatch)
    result = await preview.deploy_preview(ws, creds)
    assert result.status == "failed" and result.error
    assert "/bin/steal" not in result.error and TOKEN not in result.error
    assert cluster.calls == []


async def test_missing_chart_fails_cleanly(tmp_path, monkeypatch):
    ws = make_repo(tmp_path, chart=False)
    cluster = install_fake(monkeypatch, FakeCluster(run_id=ws.run_id))
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "no Helm chart" in (result.error or "")
    assert cluster.calls == []


async def test_unsafe_chart_never_reaches_privileged_steps(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)
    leak = ws.path / "deploy" / "helm" / "templates" / "leak.yaml"
    leak.write_text('data: {{ lookup "v1" "Secret" "kube-system" "x" }}\n')
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=ws.path, check=True)
    subprocess.run(["git", "commit", "-qm", "leak"], cwd=ws.path, check=True)
    cluster = install_fake(monkeypatch, FakeCluster(run_id=ws.run_id))
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "lookup" in (result.error or "")
    assert cluster.calls == []  # not even helm template ran


@pytest.mark.parametrize(
    "extra",
    [
        "---\napiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRoleBinding\nmetadata:\n  name: x\n",  # noqa: E501
        "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n  namespace: kube-system\n",
        "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n  annotations:\n    helm.sh/hook: pre-install\n",  # noqa: E501
    ],
)
async def test_rendered_policy_violations_stop_before_the_cluster(tmp_path, monkeypatch, extra):
    ws = make_repo(tmp_path)
    cluster = install_fake(
        monkeypatch,
        FakeCluster(run_id=ws.run_id, rendered=rendered_for(ws.run_id) + extra),
    )
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "chart rejected" in (result.error or "")
    assert cluster.commands() == ["helm template"]  # only the credential-free render ran


async def test_helm_template_failure_is_reported_scrubbed(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, fail={"helm template": f"parse error {TOKEN}"})
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "helm template failed" in (result.error or "")
    assert cluster.commands() == ["helm template"]


async def test_foreign_namespace_is_never_adopted_or_deleted(tmp_path, monkeypatch):
    ws, cluster = fixture(
        tmp_path,
        monkeypatch,
        namespace_exists=True,
        namespace_labels={"team": "payments"},
    )
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "not a preview created by this platform" in (
        result.error or ""
    )
    assert "kubectl delete" not in cluster.commands() and "kubectl apply" not in cluster.commands()
    with pytest.raises(PreviewError, match="not a preview"):
        await preview.teardown_preview(deployed(ws.run_id), CREDS)
    assert "kubectl delete" not in cluster.commands()


# ------------------------------------------------------------ failures


async def test_install_failure_cleans_up_and_scrubs(tmp_path, monkeypatch):
    ws, cluster = fixture(
        tmp_path,
        monkeypatch,
        fail={"helm upgrade": f"Error: auth failed using {TOKEN} for cluster"},
    )
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed"
    assert TOKEN not in (result.error or "") and "[redacted]" in (result.error or "")
    commands = cluster.commands()
    assert commands[-2:] == ["helm uninstall", "kubectl delete"]  # partial work removed
    assert not cluster.namespace_exists


async def test_incomplete_cleanup_is_reported_for_the_ttl_sweep(tmp_path, monkeypatch):
    ws, cluster = fixture(
        tmp_path,
        monkeypatch,
        fail={"helm upgrade": "boom", "kubectl delete": "forbidden"},
    )
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "TTL sweep" in (result.error or "")
    assert result.namespace == preview.preview_namespace(ws.run_id)


async def test_post_install_audit_tears_down_a_policy_violation(tmp_path, monkeypatch):
    bad = (
        rendered_for(uuid.uuid4()) + "---\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: x\n"
    )
    ws, cluster = fixture(tmp_path, monkeypatch, installed_manifest=bad)
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "failed" and "installed manifests broke policy" in (result.error or "")
    assert cluster.commands()[-2:] == ["helm uninstall", "kubectl delete"]


async def test_no_public_address_still_deploys_without_a_url(tmp_path, monkeypatch):
    ws, _ = fixture(tmp_path, monkeypatch, ingress={"items": []})
    result = await preview.deploy_preview(ws, CREDS)
    assert result.status == "deployed" and result.url is None


# --------------------------------------------------------- url discovery


def test_discover_url_prefers_ingress_then_load_balancer():
    ingress = json.dumps({"items": [{"spec": {"rules": [{"host": "A.Example.com"}]}}]})
    assert preview.discover_url(ingress, "{}") == "http://a.example.com"
    tls = json.dumps({"items": [{"spec": {"tls": [{}], "rules": [{"host": "x.example.com"}]}}]})
    assert preview.discover_url(tls, "{}") == "https://x.example.com"
    lb = json.dumps(
        {
            "items": [
                {
                    "spec": {"type": "LoadBalancer", "ports": [{"port": 8080}]},
                    "status": {"loadBalancer": {"ingress": [{"ip": "203.0.113.7"}]}},
                }
            ]
        }
    )
    assert preview.discover_url('{"items": []}', lb) == "http://203.0.113.7:8080"
    https_lb = lb.replace("8080", "443")
    assert preview.discover_url("{}", https_lb) == "https://203.0.113.7"


@pytest.mark.parametrize(
    "host", ["*.example.com", "evil.com/path", "a b", "ex ample", "http://x", "x.com:80@y", ""]
)
def test_discover_url_rejects_odd_hosts(host):
    ingress = json.dumps({"items": [{"spec": {"rules": [{"host": host}]}}]})
    assert preview.discover_url(ingress, "{}") is None


def test_discover_url_tolerates_garbage():
    assert preview.discover_url("not json", "also not") is None


# ------------------------------------------------------------- teardown


async def test_teardown_removes_release_then_namespace_and_is_idempotent(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, namespace_exists=True)
    deployment = deployed(ws.run_id)
    await preview.teardown_preview(deployment, CREDS)
    assert cluster.commands() == ["kubectl get namespace", "helm uninstall", "kubectl delete"]
    delete = cluster.calls[-1].argv
    assert preview.preview_namespace(ws.run_id) in delete and "--ignore-not-found=true" in delete
    uninstall = cluster.calls[1].argv
    assert preview.preview_release(ws.run_id) in uninstall and "--no-hooks" in uninstall
    assert not cluster.namespace_exists

    before = len(cluster.calls)
    await preview.teardown_preview(deployment, CREDS)  # second call: already gone
    assert cluster.commands()[before:] == ["kubectl get namespace"]


async def test_teardown_tolerates_a_missing_release(tmp_path, monkeypatch):
    ws, cluster = fixture(
        tmp_path,
        monkeypatch,
        namespace_exists=True,
        fail={"helm uninstall": "Error: uninstall: Release not loaded: x: release: not found"},
    )
    await preview.teardown_preview(deployed(ws.run_id, status="failed"), CREDS)
    assert not cluster.namespace_exists


async def test_teardown_reports_delete_failures(tmp_path, monkeypatch):
    ws, _ = fixture(
        tmp_path, monkeypatch, namespace_exists=True, fail={"kubectl delete": f"forbidden {TOKEN}"}
    )
    with pytest.raises(PreviewError) as err:
        await preview.teardown_preview(deployed(ws.run_id), CREDS)
    assert "namespace delete failed" in str(err.value) and TOKEN not in str(err.value)


async def test_teardown_refuses_namespaces_it_did_not_derive(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, namespace_exists=True)
    for hostile in ("kube-system", "production", f"asep-preview-{uuid.uuid4().hex}"):
        bad = deployed(ws.run_id).model_copy(update={"namespace": hostile})
        with pytest.raises(PreviewError, match="not this run's preview"):
            await preview.teardown_preview(bad, CREDS)
    assert cluster.calls == []


async def test_teardown_of_finished_records_does_nothing(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, namespace_exists=True)
    for status in ("deleted", "simulated"):
        await preview.teardown_preview(deployed(ws.run_id, status=status), {})
    assert cluster.calls == []


async def test_teardown_for_run_needs_only_the_run_id(tmp_path, monkeypatch):
    ws, cluster = fixture(tmp_path, monkeypatch, namespace_exists=True)
    await preview.teardown_preview_for_run(ws.run_id, CREDS)
    assert not cluster.namespace_exists


# ----------------------------------------------------------- ttl / sweep


def test_is_expired_uses_the_clock():
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    assert not preview.is_expired(deployed(run_id, hours=1), now)
    assert preview.is_expired(deployed(run_id, hours=1), now + timedelta(hours=2))
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
    naive = deployed(run_id).model_copy(update={"expires_at": past})
    assert preview.is_expired(naive)  # naive timestamps are read as UTC


def ns_item(run_id: uuid.UUID, expires: str | None, name: str | None = None):
    meta: dict = {"name": name or preview.preview_namespace(run_id)}
    if expires is not None:
        meta["annotations"] = {preview.ANNOTATION_EXPIRES: expires}
    return {"metadata": meta}


async def test_sweep_deletes_only_expired_labelled_namespaces(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    expired, fresh, junk = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    items = [
        ns_item(expired, (now - timedelta(hours=1)).isoformat()),
        ns_item(fresh, (now + timedelta(hours=5)).isoformat()),
        ns_item(junk, "not-a-date"),
        ns_item(junk, None),
        ns_item(junk, (now - timedelta(hours=9)).isoformat(), name="kube-system"),
        ns_item(junk, (now - timedelta(hours=9)).isoformat(), name="asep-preview-short"),
    ]
    cluster = install_fake(
        monkeypatch, FakeCluster(run_id=expired, namespaces=items, namespace_exists=True)
    )
    result = await preview.sweep_expired_previews(CREDS, now=now)
    assert result.cleaned == [preview.preview_namespace(expired)] and result.failed == []
    listing = cluster.calls[0].argv
    assert "-l" in listing and f"{preview.LABEL_MANAGED}={preview.MANAGED_VALUE}" in listing
    deletes = [c for c in cluster.calls if c.argv[1:3] == ["--request-timeout=30s", "delete"]]
    assert len(deletes) == 1 and preview.preview_namespace(expired) in deletes[0].argv


async def test_sweep_records_failures_and_keeps_going(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    first, second = uuid.uuid4(), uuid.uuid4()
    items = [ns_item(r, (now - timedelta(hours=1)).isoformat()) for r in (first, second)]
    install_fake(
        monkeypatch,
        FakeCluster(
            run_id=first, namespaces=items, namespace_exists=True, namespace_labels={"x": "y"}
        ),
    )
    result = await preview.sweep_expired_previews(CREDS, now=now)
    # labels do not match either run id, so both are refused and reported, none deleted
    assert result.cleaned == [] and len(result.failed) == 2
