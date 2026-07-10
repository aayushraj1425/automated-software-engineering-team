"""The Docker sandbox: plan detection and the container lifecycle.

Docker itself is faked — a recorded stand-in for the `docker` CLI — so these
tests run offline and assert the exact sequence of calls: create, copy in,
install (network ON), disconnect the network, test (network OFF), remove.
Design note: docs/architecture/SANDBOX_EXECUTION.md.
"""

import uuid
from pathlib import Path

from engine.config import get_settings
from engine.sandbox import runner as sandbox
from engine.sandbox.runner import detect_plan, run_sandbox

RUN_ID = uuid.uuid4()


# --- plan detection -----------------------------------------------------


def test_requirements_txt_means_python(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.image == "python:3.12-slim"
    assert plan.install is not None and "requirements.txt" in plan.install
    assert plan.test == "python -m pytest -q"


def test_pyproject_means_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.install == "pip install -q . pytest"


def test_config_only_pyproject_does_not_install_the_project(tmp_path: Path):
    # pyproject.toml carrying only tool config is not an installable package;
    # `pip install .` would error, so the plan must skip it and just add pytest.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n")
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.install == "pip install -q pytest"


def test_package_json_needs_a_test_script(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest run"}}')
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.image == "node:20-slim"
    assert plan.install == "npm install"  # no lockfile in this workspace
    assert plan.test == "npm test"

    (tmp_path / "package-lock.json").write_text("{}")
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.install == "npm ci"


def test_package_json_without_tests_is_not_a_plan(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}')
    assert detect_plan(tmp_path) is None


def test_package_json_is_parsed_not_grepped(tmp_path: Path):
    # The word "test" appears — but not as a script. A grep would false-positive.
    (tmp_path / "package.json").write_text('{"dependencies": {"test-utils": "1.0.0"}}')
    assert detect_plan(tmp_path) is None


def test_malformed_package_json_is_not_a_plan(tmp_path: Path):
    (tmp_path / "package.json").write_text("{not json at all")
    assert detect_plan(tmp_path) is None


def test_bare_test_files_get_pytest(tmp_path: Path):
    (tmp_path / "test_app.py").write_text("def test_ok():\n    assert True\n")
    plan = detect_plan(tmp_path)
    assert plan is not None
    assert plan.install == "pip install -q pytest"


def test_unrecognized_workspace_has_no_plan(tmp_path: Path):
    (tmp_path / "README.md").write_text("# nothing to run\n")
    assert detect_plan(tmp_path) is None


def test_vendored_test_files_do_not_trigger_a_plan(tmp_path: Path):
    # test_*.py inside node_modules / .git must not look like the run's tests.
    for vendored in ("node_modules/pkg", ".git/hooks"):
        folder = tmp_path / vendored
        folder.mkdir(parents=True)
        (folder / "test_vendored.py").write_text("def test_x():\n    assert True\n")
    assert detect_plan(tmp_path) is None

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "test_real.py").write_text("def test_y():\n    assert True\n")
    plan = detect_plan(tmp_path)
    assert plan is not None and plan.install == "pip install -q pytest"


# --- container lifecycle (fake docker) ----------------------------------


class FakeDocker:
    """Records every docker call; per-command exit codes and output."""

    def __init__(self, fails: dict[str, tuple[int, str]] | None = None):
        self.calls: list[tuple[str, ...]] = []
        self.fails = fails or {}

    async def __call__(self, *args: str, timeout: int = 60) -> tuple[int, str]:
        self.calls.append(args)
        key = args[0] if args[0] != "exec" else f"exec:{args[-1]}"
        return self.fails.get(key, (0, "ok"))

    def commands(self) -> list[str]:
        return [c[0] for c in self.calls]


def _python_workspace(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("pytest\n")
    return tmp_path


def _enable_sandbox(monkeypatch):
    monkeypatch.setattr(get_settings(), "sandbox_enabled", True)


async def test_a_passing_run_walks_the_full_lifecycle(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker()
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "passed"
    assert result.exit_code == 0
    # version check, create, copy in, install, unplug, test, remove — in order.
    assert fake.commands() == ["version", "run", "cp", "exec", "network", "exec", "rm"]
    network_call = fake.calls[4]
    assert network_call[:2] == ("network", "disconnect")
    assert fake.calls[-1][:2] == ("rm", "-f")  # container removed at the end
    run_call = fake.calls[1]
    # Hardening flags: no capabilities, no privilege escalation, reap label.
    assert "--cap-drop" in run_call and "ALL" in run_call
    assert "--security-opt" in run_call and "no-new-privileges" in run_call
    assert "--label" in run_call and "asep.sandbox=1" in run_call


async def test_failing_tests_fail_the_result_with_output(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker(fails={"exec:python -m pytest -q": (1, "FAILED test_app.py::test_x")})
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "failed"
    assert result.exit_code == 1
    assert "exit code 1" in result.reason
    assert "FAILED test_app.py" in result.output
    assert fake.calls[-1][:2] == ("rm", "-f")  # cleaned up despite the failure


async def test_a_broken_install_never_reaches_the_tests(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker(
        fails={"exec:pip install -q -r requirements.txt pytest": (1, "no matching distribution")}
    )
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "failed"
    assert result.reason == "dependency install failed"
    assert "network" not in fake.commands()  # unplug step never happened
    assert fake.commands().count("exec") == 1  # the test command never ran


async def test_a_test_timeout_reads_as_a_timeout(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker(fails={"exec:python -m pytest -q": (-1, "timed out after 300s")})
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "failed"
    assert "timed out" in result.reason
    assert result.exit_code is None


async def test_missing_docker_skips_instead_of_failing(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker(fails={"version": (-2, "docker is not installed")})
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "skipped"
    assert result.reason == "docker is not available"
    assert fake.commands() == ["version"]  # nothing else was attempted


async def test_required_mode_fails_when_docker_is_missing(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    monkeypatch.setattr(get_settings(), "sandbox_required", True)
    fake = FakeDocker(fails={"version": (-2, "docker is not installed")})
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "failed"
    assert "SANDBOX_REQUIRED" in result.reason


async def test_disabled_sandbox_skips_before_touching_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "sandbox_enabled", False)
    fake = FakeDocker()
    monkeypatch.setattr(sandbox, "_docker", fake)

    result = await run_sandbox(_python_workspace(tmp_path), RUN_ID)

    assert result.status == "skipped"
    assert fake.calls == []


async def test_a_workspace_with_nothing_to_run_skips(tmp_path, monkeypatch):
    _enable_sandbox(monkeypatch)
    fake = FakeDocker()
    monkeypatch.setattr(sandbox, "_docker", fake)

    (tmp_path / "notes.md").write_text("no code here\n")
    result = await run_sandbox(tmp_path, RUN_ID)

    assert result.status == "skipped"
    assert "no recognized test setup" in result.reason
    assert fake.calls == []
