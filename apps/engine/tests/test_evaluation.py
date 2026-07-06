"""The evaluation harness runs a golden task through the whole pipeline."""

import pytest

from engine.config import get_settings
from engine.evaluation import GOLDEN_TASKS, prepare_fixture_repo, run_golden_task


@pytest.fixture(autouse=True)
def workspaces_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspaces_dir", str(tmp_path / "workspaces"))


async def test_golden_task_passes_offline(prepared_db, tmp_path):
    origin = prepare_fixture_repo(tmp_path / "origin")
    assert (origin / "app" / "main.py").is_file()

    score = await run_golden_task(origin, GOLDEN_TASKS[0])

    assert score.planned, score.error
    assert score.completed, score.error
    assert score.committed
    assert score.diff_matched is None  # offline mode never judges the diff
    assert score.passed
