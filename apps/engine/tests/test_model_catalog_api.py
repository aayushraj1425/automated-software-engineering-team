"""Exercise selection evidence through the real run API, with offline agents."""

from engine.config import get_settings
from engine.llm.router import selected_model_var
from tests.conftest import auth_headers
from tests.test_model_catalog import entry


async def test_catalog_requires_auth_and_returns_only_metadata(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_catalog", [entry()])
    assert (await client.get("/v1/models")).status_code == 401
    response = await client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == [entry().model_dump()]


async def test_run_records_selections_across_planning_and_execution(client, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "workspaces_dir", str(tmp_path / "workspaces"))
    monkeypatch.setattr(settings, "model_catalog", [entry(), entry("senior", 4, 5)])
    headers = auth_headers("model_selection_run")
    response = await client.post(
        "/v1/runs",
        headers=headers,
        json={"request": "Add status", "repository_url": "https://github.com/acme/demo"},
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    response = await client.post(
        f"/v1/runs/{run_id}/decision", headers=headers, json={"approved": True}
    )
    assert response.status_code == 200, response.text
    detail = (await client.get(f"/v1/runs/{run_id}", headers=headers)).json()
    assert detail["status"] == "completed", detail
    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    picks = [event for event in events if event["type"] == "model.selected"]
    assert [event["agent"] for event in picks] == [
        "product_manager",
        "backend",
        "frontend",
        "devops",
        "reviewer",
    ]
    assert all(event["payload"]["model"] == "fake" for event in picks)
    assert picks[0]["payload"]["configured_model"] == "anthropic/senior"
    assert picks[1]["payload"]["configured_model"] == "anthropic/engineer"
    assert all(event["task_id"] is not None for event in picks[1:4])
    assert selected_model_var.get() is None
