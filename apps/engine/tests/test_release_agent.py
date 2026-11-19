"""Release Engineer functions, the preview_check tool, and the CLI runner."""

import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from engine.agents import release
from engine.agents.tools import TOOLS, call_tool, schemas_for
from engine.deploy import check as check_cli
from engine.deploy import cli, preview
from engine.deploy.contracts import PreviewDeployment, PreviewOptions, SmokeResult
from engine.deploy.safety import PreviewError
from tests.preview_support import (
    FIXTURE_CHART,
    TOKEN,
    FakeCluster,
    install_fake,
    kubeconfig_text,
    make_repo,
)

CREDS = {"kubeconfig": kubeconfig_text()}


def deployment(
    run_id,
    status: Literal["deployed", "failed", "deleted", "simulated"] = "deployed",
    url: str | None = "https://preview.example.com",
    smoke=None,
    error=None,
):
    return PreviewDeployment(
        run_id=run_id,
        namespace=preview.preview_namespace(run_id),
        url=url,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        source_sha="a" * 40,
        smoke=smoke,
        error=error,
    )


class Events:
    def __init__(self):
        self.items: list[tuple[str, dict]] = []

    async def __call__(self, name: str, payload: dict) -> None:
        self.items.append((name, payload))


# ------------------------------------------------------------ release flow


async def test_simulated_release_is_labelled_and_has_no_url(tmp_path):
    ws = make_repo(tmp_path)
    events = Events()
    result = await release.run_preview_release(ws, {}, on_event=events)
    assert result.status == "simulated" and result.url is None and result.smoke is None
    assert [name for name, _ in events.items] == ["deploy.started", "deploy.finished"]
    finished = events.items[1][1]
    assert finished["simulated"] is True and finished["url"] is None
    evidence = release.format_deploy_evidence(result)
    assert "SIMULATED" in evidence and "URL:" not in evidence and "http" not in evidence
    assert "passed" not in evidence


async def test_live_release_deploys_then_smoke_tests(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)
    run_id = ws.run_id
    calls = []

    async def fake_deploy(workspace, credentials, *, options=None, expected_sha=None):
        calls.append(("deploy", expected_sha, options))
        return deployment(run_id)

    async def fake_smoke(url, *, paths=None, timeout_seconds=30):
        calls.append(("smoke", url, paths))
        return SmokeResult(passed=True, checks=[{"path": "/healthz", "status": 200, "ok": True}])

    monkeypatch.setattr(release, "deploy_preview", fake_deploy)
    monkeypatch.setattr(release, "run_cloud_smoke_tests", fake_smoke)
    events = Events()
    options = PreviewOptions(smoke_paths=["/healthz", "/api/ping"])
    result = await release.run_preview_release(
        ws, CREDS, options=options, expected_sha="a" * 40, on_event=events
    )
    assert result.smoke is not None and result.smoke.passed
    assert calls[0][:2] == ("deploy", "a" * 40)
    assert calls[1] == ("smoke", "https://preview.example.com", ["/healthz", "/api/ping"])
    finished = events.items[-1][1]
    assert finished["status"] == "deployed" and finished["smoke_passed"] is True
    assert finished["simulated"] is False
    # events carry no credential material
    assert TOKEN not in repr(events.items)


async def test_failed_deploy_skips_smoke_and_reports(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)

    async def fake_deploy(*a, **k):
        return deployment(ws.run_id, status="failed", url=None, error="helm upgrade failed: x")

    async def no_smoke(*a, **k):
        raise AssertionError("no smoke on a failed deploy")

    monkeypatch.setattr(release, "deploy_preview", fake_deploy)
    monkeypatch.setattr(release, "run_cloud_smoke_tests", no_smoke)
    result = await release.run_preview_release(ws, CREDS)
    assert result.status == "failed" and result.smoke is None
    assert "failed" in release.format_deploy_evidence(result)


async def test_deployed_without_url_records_a_failed_smoke(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)

    async def fake_deploy(*a, **k):
        return deployment(ws.run_id, url=None)

    monkeypatch.setattr(release, "deploy_preview", fake_deploy)
    result = await release.run_preview_release(ws, CREDS)
    assert result.smoke is not None and not result.smoke.passed
    assert "no Ingress host" in (result.smoke.error or "")


async def test_end_to_end_with_scripted_cluster_and_mocked_http(tmp_path, monkeypatch):
    import httpx

    from engine.deploy import smoke as smoke_mod

    ws = make_repo(tmp_path)
    ingress = {"items": [{"spec": {"tls": [{}], "rules": [{"host": "preview.example.com"}]}}]}
    cluster = install_fake(monkeypatch, FakeCluster(run_id=ws.run_id, ingress=ingress))

    async def resolve(host, port):
        return ["93.184.216.34"]

    real_run_smoke = smoke_mod.run_smoke

    async def run_smoke(url, paths, timeout, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
        kw["resolver"] = resolve
        return await real_run_smoke(url, paths, timeout, **kw)

    monkeypatch.setattr(smoke_mod, "run_smoke", run_smoke)
    result = await release.run_preview_release(ws, CREDS, expected_sha=ws.base_sha)
    assert result.status == "deployed" and result.smoke is not None and result.smoke.passed
    evidence = release.format_deploy_evidence(result)
    assert (
        "https://preview.example.com" in evidence
        and "/healthz" in evidence
        and "passed" in evidence
    )
    assert "SIMULATED" not in evidence

    cleaned = await release.cleanup_preview(result, CREDS)
    assert cleaned.status == "deleted" and cleaned.url is None
    assert not cluster.namespace_exists
    again = await release.cleanup_preview(cleaned, CREDS)  # idempotent: already deleted
    assert again.status == "deleted"


def test_evidence_escapes_table_cells_and_marks_failures():
    run_id = uuid.uuid4()
    smoke = SmokeResult(
        passed=False,
        checks=[
            {
                "path": "/a",
                "status": 500,
                "ok": False,
                "error": "bad | pipe\nnewline",
                "attempts": 4,
            }
        ],
        error="1 of 1 checks failed",
    )
    text = release.format_deploy_evidence(deployment(run_id, smoke=smoke))
    assert "FAILED" in text and "bad / pipe newline" in text
    assert text.count("\n| `/a`") == 1
    assert f"`{'a' * 12}`" in text and "Expires:" in text


# --------------------------------------------------------- readiness / tool


async def test_readiness_accepts_the_fixture_and_rejects_bad_charts(tmp_path):
    ws = make_repo(tmp_path)
    ready = await release.assess_release_readiness(ws)
    assert ready.ready and ready.problems == []
    bad = await release.assess_release_readiness(ws, PreviewOptions(chart_path="nope/chart"))
    assert not bad.ready and "no Helm chart" in bad.problems[0]
    escape = await release.assess_release_readiness(ws, PreviewOptions(chart_path="../x"))
    assert not escape.ready and "escapes" in escape.problems[0]


async def test_readiness_renders_with_helm_when_available(tmp_path, monkeypatch):
    ws = make_repo(tmp_path)
    cluster = install_fake(monkeypatch, FakeCluster(run_id=ws.run_id))
    ready = await release.assess_release_readiness(ws)
    assert ready.ready and ready.rendered
    assert cluster.commands() == ["helm template"] and cluster.calls[0].kubeconfig is None

    bad_render = rendered = FakeCluster(
        run_id=ws.run_id,
        rendered="apiVersion: rbac.authorization.k8s.io/v1\nkind: ClusterRole\nmetadata:\n  name: x\n",  # noqa: E501
    )
    install_fake(monkeypatch, bad_render)
    verdict = await release.assess_release_readiness(ws)
    assert not verdict.ready and rendered.commands() == ["helm template"]


def test_preview_check_tool_is_registered_and_credential_free():
    assert "preview_check" in TOOLS
    schema = schemas_for(("preview_check",))[0]["function"]
    assert set(schema["parameters"]["properties"]) == {"chart_path", "values_file"}
    assert "credential" not in str(schema["parameters"]).lower()


async def test_preview_check_tool_reports_for_the_agent(tmp_path):
    ws = make_repo(tmp_path)
    ok = await call_tool(ws, ("preview_check",), "preview_check", {})
    assert ok.startswith("chart accepted")
    bad = await call_tool(ws, ("preview_check",), "preview_check", {"chart_path": "../etc"})
    assert bad.startswith("chart rejected") and "escapes the workspace" in bad
    denied = await call_tool(ws, ("read_file",), "preview_check", {})
    assert denied.startswith("ERROR")
    oops = await call_tool(ws, ("preview_check",), "preview_check", {"chart_path": ""})
    assert oops.startswith("chart rejected") or oops.startswith("ERROR")


# ------------------------------------------------------------- check command


def test_check_command_accepts_fixture_and_rejects_bad_chart(tmp_path, capsys):
    assert check_cli.main(["--chart", str(FIXTURE_CHART), "--no-render"]) == 0
    assert "chart accepted" in capsys.readouterr().out

    bad = tmp_path / "bad"
    shutil.copytree(FIXTURE_CHART, bad)
    (bad / "templates" / "x.yaml").write_text('a: {{ lookup "v1" "Secret" "n" "m" }}\n')
    assert check_cli.main(["--chart", str(bad), "--no-render"]) == 1
    assert "chart rejected" in capsys.readouterr().out


def test_check_command_runs_as_a_module():
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "engine.deploy.check", "--chart", str(FIXTURE_CHART), "--no-render"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0 and "chart accepted" in proc.stdout


# ----------------------------------------------------------------- cli runner


async def test_cli_runner_refuses_other_programs_and_odd_arguments(tmp_path):
    env = cli.build_env(tmp_path, None)
    for argv in (["bash", "-c", "id"], ["git", "status"], [], ["helm\x00", "x"]):
        with pytest.raises(PreviewError):
            await cli.run_cli(argv, env=env, timeout=5, cwd=tmp_path)


def test_cli_env_is_an_allow_list(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("GEMINI_API_KEY", "k-secret")
    env = cli.build_env(tmp_path, tmp_path / "kubeconfig")
    assert "DATABASE_URL" not in env and "GEMINI_API_KEY" not in env
    assert env["KUBECONFIG"] == str(tmp_path / "kubeconfig")
    for key in ("HOME", "HELM_CACHE_HOME", "HELM_CONFIG_HOME", "HELM_DATA_HOME", "HELM_PLUGINS"):
        assert Path(env[key]).is_relative_to(tmp_path)
    assert "KUBECONFIG" not in cli.build_env(tmp_path, None)


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is not installed")
async def test_cli_runner_really_starts_a_process_without_a_shell(tmp_path):
    env = cli.build_env(tmp_path, None)
    result = await cli.run_cli(
        ["kubectl", "version", "--client"], env=env, timeout=60, cwd=tmp_path
    )
    assert result.returncode == 0 and "Client Version" in result.stdout
    assert Path(env["HOME"]).is_relative_to(tmp_path)


async def test_cli_runner_reports_missing_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(PreviewError, match="not installed"):
        await cli.run_cli(["helm", "version"], env={}, timeout=5, cwd=tmp_path)
    assert not cli.tool_available("helm") and not cli.tool_available("bash")
