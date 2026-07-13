"""External integrations: encrypted connections + Slack run-outcome notify.

INTEGRATIONS_DRY_RUN=1 (set in conftest) makes the Slack adapter skip the
network and report a dry run, so the whole path — connect → run finishes →
`integration.notified` event — runs without a real workspace. Design note:
docs/architecture/EXTERNAL_INTEGRATIONS.md.
"""

import uuid

from engine.config import get_settings
from engine.db.models import IntegrationConnection
from engine.db.session import session_scope
from tests.conftest import auth_headers

WEBHOOK = "https://hooks.slack.com/services/T000/B000/xxxxxxxxxxxx"


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _connect_slack(client, headers, url: str = WEBHOOK) -> dict:
    resp = await client.put(
        "/v1/integrations/slack", json={"config": {"webhook_url": url}}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── The connection store ────────────────────────────────────────────────────


async def test_connect_lists_without_leaking_the_secret(client):
    headers = _headers()
    created = await _connect_slack(client, headers)
    assert created["kind"] == "slack"
    assert created["enabled"] is True
    # the label is a non-secret hint, never the webhook itself
    assert "hooks.slack.com" in created["label"]
    assert WEBHOOK not in created["label"]

    listed = (await client.get("/v1/integrations", headers=headers)).json()
    assert [c["kind"] for c in listed] == ["slack"]
    assert "webhook_url" not in listed[0]


async def test_the_webhook_is_encrypted_at_rest(client):
    headers = auth_headers("user_crypto")
    await _connect_slack(client, headers)
    async with session_scope() as session:
        row = (
            await session.execute(
                IntegrationConnection.__table__.select().where(
                    IntegrationConnection.user_id == "user_crypto"
                )
            )
        ).first()
    assert row is not None
    # the raw column holds ciphertext, not the plaintext URL
    assert WEBHOOK not in row.encrypted_config


async def test_a_bad_webhook_is_rejected(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/slack",
        json={"config": {"webhook_url": "https://example.com/nope"}},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_inactive_kind_is_refused(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/jira", json={"config": {"token": "x"}}, headers=headers
    )
    assert resp.status_code == 400


async def test_connect_linear_needs_both_fields(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/linear",
        json={"config": {"api_key": "lin_api_x"}},  # missing team_id
        headers=headers,
    )
    assert resp.status_code == 422


async def test_connect_linear_labels_without_leaking_the_key(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/linear",
        json={"config": {"api_key": "lin_api_secret_value", "team_id": "TEAM-abcdef"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "linear"
    assert "Linear" in body["label"]
    assert "lin_api_secret_value" not in body["label"]


async def test_linear_has_no_test_message(client):
    headers = _headers()
    await client.put(
        "/v1/integrations/linear",
        json={"config": {"api_key": "lin_api_x", "team_id": "T-1"}},
        headers=headers,
    )
    resp = await client.post("/v1/integrations/linear/test", headers=headers)
    assert resp.status_code == 400  # test messages are Slack-only


async def test_connections_are_owner_scoped(client):
    owner = _headers()
    await _connect_slack(client, owner)
    stranger = _headers()
    listed = (await client.get("/v1/integrations", headers=stranger)).json()
    assert listed == []


async def test_delete_disconnects(client):
    headers = _headers()
    await _connect_slack(client, headers)
    resp = await client.delete("/v1/integrations/slack", headers=headers)
    assert resp.status_code == 204
    assert (await client.get("/v1/integrations", headers=headers)).json() == []


# ── The test-send endpoint ──────────────────────────────────────────────────


async def test_test_send_reports_dry_run(client):
    headers = _headers()
    await _connect_slack(client, headers)
    resp = await client.post("/v1/integrations/slack/test", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["dry_run"] is True  # dry-run in tests, no real Slack call


async def test_test_send_without_a_connection_is_404(client):
    headers = _headers()
    resp = await client.post("/v1/integrations/slack/test", headers=headers)
    assert resp.status_code == 404


# ── A finished run notifies Slack ───────────────────────────────────────────


async def test_finished_run_records_a_notified_event(client):
    headers = _headers()
    await _connect_slack(client, headers)
    url = f"https://github.com/acme/demo-{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": url},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]
    decided = await client.post(
        f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers
    )
    assert decided.status_code == 200, decided.text

    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    notified = [e for e in events if e["type"] == "integration.notified"]
    assert notified, "a finished run with a Slack connection did not notify"
    assert notified[0]["payload"]["kind"] == "slack"
    assert notified[0]["payload"]["dry_run"] is True


async def test_run_without_a_connection_emits_no_notified_event(client):
    headers = _headers()  # this user connected nothing
    url = f"https://github.com/acme/demo-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/v1/runs",
        json={"request": "Add a /status endpoint", "repository_url": url},
        headers=headers,
    )
    run_id = resp.json()["id"]
    await client.post(f"/v1/runs/{run_id}/decision", json={"approved": True}, headers=headers)

    events = (await client.get(f"/v1/runs/{run_id}/events", headers=headers)).json()
    assert not [e for e in events if e["type"] == "integration.notified"]


def test_dry_run_is_on_in_tests():
    assert get_settings().integrations_dry_run is True
