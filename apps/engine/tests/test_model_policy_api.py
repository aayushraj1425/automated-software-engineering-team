"""GET/PUT /v1/model-policy against the real database and row-level security.

The router is mounted on a small app of its own, so these tests hold whether or not
the lead has registered it in main.py yet.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from engine.api import model_policy
from engine.config import get_settings
from engine.db.session import session_scope
from engine.llm.policy import load_org_model_policy
from tests.conftest import auth_headers
from tests.test_open_source_models import LOCAL, local, paid


@pytest.fixture
async def policy_client(prepared_db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "model_catalog", [paid(), paid("senior", 4, 5), local(), local("nope")]
    )
    monkeypatch.setattr(settings, "model_evaluation_dir", "no-such-evaluation-dir")
    async with session_scope() as session:
        await session.execute(text("DELETE FROM organization_model_policies"))
        await session.commit()
    app = FastAPI()
    app.include_router(model_policy.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def admin(org="org_policy_a", user="admin_user"):
    return auth_headers(user, org_id=org, org_role="admin")


async def test_requires_auth_and_an_active_organization(policy_client):
    assert (await policy_client.get("/v1/model-policy")).status_code == 401
    response = await policy_client.get("/v1/model-policy", headers=auth_headers("solo"))
    assert response.status_code == 400
    response = await policy_client.put("/v1/model-policy", headers=auth_headers("solo"), json={})
    assert response.status_code == 400


async def test_default_policy_keeps_open_source_out_and_explains_why(policy_client):
    response = await policy_client.get("/v1/model-policy", headers=admin())
    assert response.status_code == 200
    body = response.json()
    assert body["level_pins"] == {} and body["allow_open_source_auto"] is False
    assert body["updated_at"] is None
    statuses = {s["model_id"]: s for s in body["open_source_models"]}
    assert set(statuses) == {LOCAL, "openai_compatible/nope"}
    assert not statuses[LOCAL]["eligible_for_auto"]
    assert "eval_open_model.py" in statuses[LOCAL]["reason"]
    assert "localhost" not in response.text  # endpoint URLs never leave the server


async def test_admin_writes_and_any_member_reads(policy_client):
    body = {"level_pins": {"senior": "anthropic/senior"}, "allow_open_source_auto": True}
    response = await policy_client.put("/v1/model-policy", headers=admin(), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["allow_open_source_auto"] is True
    member = auth_headers("member_user", org_id="org_policy_a", org_role="member")
    read = await policy_client.get("/v1/model-policy", headers=member)
    assert read.json()["level_pins"] == {"senior": "anthropic/senior"}
    assert read.json()["allow_open_source_auto"] is True
    # A second write replaces rather than merges, and can switch the opt-in back off.
    again = await policy_client.put("/v1/model-policy", headers=admin(), json={})
    assert again.json()["level_pins"] == {} and again.json()["allow_open_source_auto"] is False
    assert again.json()["updated_at"] is not None


async def test_only_owner_or_admin_may_write(policy_client):
    for role in ("member", None):
        headers = auth_headers("plain_user", org_id="org_policy_a", org_role=role)
        response = await policy_client.put("/v1/model-policy", headers=headers, json={})
        assert response.status_code == 403
    owner = auth_headers("owner_user", org_id="org_policy_a", org_role="owner")
    assert (await policy_client.put("/v1/model-policy", headers=owner, json={})).status_code == 200


async def test_pins_are_validated_against_the_catalog(policy_client):
    for pins in (
        {"wizard": "anthropic/senior"},
        {"senior": "anthropic/missing"},
    ):
        response = await policy_client.put(
            "/v1/model-policy", headers=admin(), json={"level_pins": pins}
        )
        assert response.status_code == 422, pins
    response = await policy_client.put(
        "/v1/model-policy", headers=admin(), json={"unknown_field": True}
    )
    assert response.status_code == 422
    # Nothing invalid was stored.
    assert (await policy_client.get("/v1/model-policy", headers=admin())).json()["level_pins"] == {}


async def test_pin_to_tool_less_model_is_rejected(policy_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_catalog", [paid(supports_tools=False)])
    response = await policy_client.put(
        "/v1/model-policy", headers=admin(), json={"level_pins": {"engineer": "anthropic/engineer"}}
    )
    assert response.status_code == 422 and "tools" in response.text


async def test_policies_are_isolated_between_organizations(policy_client):
    await policy_client.put(
        "/v1/model-policy",
        headers=admin("org_policy_a"),
        json={"allow_open_source_auto": True, "level_pins": {"engineer": "anthropic/engineer"}},
    )
    other = (await policy_client.get("/v1/model-policy", headers=admin("org_policy_b"))).json()
    assert other["allow_open_source_auto"] is False and other["level_pins"] == {}


async def test_runner_loader_reads_the_stored_policy(policy_client):
    await policy_client.put(
        "/v1/model-policy",
        headers=admin("org_policy_loader"),
        json={"allow_open_source_auto": True, "level_pins": {"support": "anthropic/engineer"}},
    )
    async with session_scope() as session:
        policy = await load_org_model_policy(session, "org_policy_loader")
        none = await load_org_model_policy(session, "org_policy_without_row")
        no_org = await load_org_model_policy(session, None)
    assert policy.allow_open_source_auto is True
    assert policy.level_pins == {"support": "anthropic/engineer"}
    assert not none.allow_open_source_auto and none.level_pins == {}
    assert not no_org.allow_open_source_auto


async def test_catalog_endpoint_hides_endpoint_and_reports_verified_evaluation(
    prepared_db, monkeypatch
):
    from engine.api import models as models_api

    settings = get_settings()
    monkeypatch.setattr(settings, "model_catalog", [local(evaluated=True), paid()])
    monkeypatch.setattr(settings, "model_evaluation_dir", "no-such-evaluation-dir")
    app = FastAPI()
    app.include_router(models_api.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    by_id = {m["id"]: m for m in response.json()}
    # The operator's own flag is reported as unverified: there are no results.
    assert by_id[LOCAL]["evaluated"] is False
    assert "base_url" not in by_id[LOCAL] and "localhost" not in response.text
