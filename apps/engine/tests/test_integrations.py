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
    # every current kind has an adapter, so the deny-by-default gate is
    # proven with a kind that does not exist at all.
    resp = await client.put(
        "/v1/integrations/asana", json={"config": {"token": "x"}}, headers=headers
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


_JIRA_CONFIG = {
    "base_url": "https://acme.atlassian.net",
    "email": "dev@acme.test",
    "api_token": "jira_secret_token",
    "project_key": "ENG",
}


async def test_connect_jira_labels_without_leaking_the_token(client):
    headers = _headers()
    resp = await client.put("/v1/integrations/jira", json={"config": _JIRA_CONFIG}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "jira"
    # the label carries the project key and host, never the token
    assert "ENG" in body["label"]
    assert "acme.atlassian.net" in body["label"]
    assert "jira_secret_token" not in body["label"]


async def test_connect_jira_needs_all_fields(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/jira",
        json={"config": {"base_url": "https://acme.atlassian.net", "email": "dev@acme.test"}},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_connect_jira_requires_https(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/jira",
        json={"config": {**_JIRA_CONFIG, "base_url": "http://acme.atlassian.net"}},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_connect_gitlab_stores_token_and_defaults_base_url(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/gitlab",
        json={"config": {"token": "glpat-secret-token"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "gitlab"
    assert "gitlab.com" in body["label"]  # default base URL host
    assert "glpat-secret-token" not in body["label"]


async def test_connect_gitlab_needs_a_token(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/gitlab",
        json={"config": {"base_url": "https://gitlab.com"}},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_gitlab_is_not_an_issue_tracker(client):
    """GitLab is a git host, not a work-item push target."""
    from engine.integrations.issues import ISSUE_TRACKER_KINDS

    assert "gitlab" not in ISSUE_TRACKER_KINDS


def test_parse_gitlab_repo_recognizes_nested_paths():
    from engine.integrations.gitlab import parse_gitlab_repo

    assert parse_gitlab_repo("https://gitlab.com/acme/demo") == "acme/demo"
    assert parse_gitlab_repo("https://gitlab.com/acme/team/demo.git") == "acme/team/demo"
    assert parse_gitlab_repo("git@gitlab.com:acme/demo.git") == "acme/demo"
    assert parse_gitlab_repo("https://github.com/acme/demo") is None
    assert parse_gitlab_repo("C:/tmp/fixture-repo") is None


async def test_open_merge_request_is_dry_run_offline():
    from engine.integrations.gitlab import open_merge_request

    url = await open_merge_request(
        {"token": "x", "base_url": "https://gitlab.com"},
        "https://gitlab.com/acme/demo",
        "asep/run-1",
        "main",
        "Add a thing",
        "body",
    )
    assert url == "https://gitlab.com/acme/demo/-/merge_requests/dry-run"


def test_connection_repo_path_recognizes_the_self_hosted_instance():
    from engine.integrations.gitlab import connection_repo_path

    config = {"token": "x", "base_url": "https://git.acme.dev"}
    assert connection_repo_path(config, "https://git.acme.dev/team/demo") == "team/demo"
    assert connection_repo_path(config, "https://git.acme.dev/team/sub/demo.git") == "team/sub/demo"
    assert connection_repo_path(config, "git@git.acme.dev:team/demo.git") == "team/demo"
    assert connection_repo_path(config, "https://gitlab.com/acme/demo") == "acme/demo"  # SaaS still
    assert connection_repo_path(config, "https://github.com/acme/demo") is None
    assert connection_repo_path(config, "https://gitlab.acme.dev.evil.io/x/y") is None


async def test_self_hosted_merge_request_targets_the_connection_base_url():
    from engine.integrations.gitlab import open_merge_request

    url = await open_merge_request(
        {"token": "x", "base_url": "https://git.acme.dev"},
        "https://git.acme.dev/team/demo",
        "asep/run-1",
        "main",
        "Add a thing",
        "body",
    )
    assert url == "https://git.acme.dev/team/demo/-/merge_requests/dry-run"


async def test_host_connection_resolves_a_self_hosted_gitlab(client, prepared_db):
    import uuid as _uuid

    from engine.db.session import session_scope
    from engine.integrations.hosts import host_connection, push_credential

    user = f"selfhost_{_uuid.uuid4().hex[:8]}"
    await client.put(
        "/v1/integrations/gitlab",
        json={"config": {"token": "glpat-self", "base_url": "https://git.acme.dev"}},
        headers=auth_headers(user),
    )

    async with session_scope() as db:
        host = await host_connection(db, user, "https://git.acme.dev/team/demo")
        assert host is not None and host[0] == "gitlab"
        assert push_credential(host) == ("oauth2", "glpat-self")

        # GitHub URLs never consult the connection; a foreign host stays None.
        assert await host_connection(db, user, "https://github.com/acme/demo") is None
        assert await host_connection(db, user, "https://code.other.dev/a/b") is None
        # And without any connection there is nothing to match against.
        assert await host_connection(db, "nobody", "https://git.acme.dev/team/demo") is None


async def test_connect_bitbucket_labels_without_leaking_the_password(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/bitbucket",
        json={"config": {"username": "dev-user", "app_password": "ATBB-secret"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "bitbucket"
    assert "dev-user" in body["label"]
    assert "ATBB-secret" not in body["label"]


async def test_connect_bitbucket_needs_both_fields(client):
    headers = _headers()
    resp = await client.put(
        "/v1/integrations/bitbucket",
        json={"config": {"username": "dev-user"}},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_bitbucket_is_not_an_issue_tracker(client):
    """Bitbucket is a git host, not a work-item push target."""
    from engine.integrations.issues import ISSUE_TRACKER_KINDS

    assert "bitbucket" not in ISSUE_TRACKER_KINDS


def test_parse_bitbucket_repo_recognizes_workspace_paths():
    from engine.integrations.bitbucket import parse_bitbucket_repo

    assert parse_bitbucket_repo("https://bitbucket.org/acme/demo") == "acme/demo"
    assert parse_bitbucket_repo("https://bitbucket.org/acme/demo.git") == "acme/demo"
    assert parse_bitbucket_repo("git@bitbucket.org:acme/demo.git") == "acme/demo"
    assert parse_bitbucket_repo("https://gitlab.com/acme/demo") is None
    assert parse_bitbucket_repo("C:/tmp/fixture-repo") is None


async def test_open_bitbucket_pull_request_is_dry_run_offline():
    from engine.integrations.bitbucket import open_pull_request

    url = await open_pull_request(
        {"username": "dev-user", "app_password": "x"},
        "https://bitbucket.org/acme/demo",
        "asep/run-1",
        "main",
        "Add a thing",
        "body",
    )
    assert url == "https://bitbucket.org/acme/demo/pull-requests/dry-run"


async def test_host_connection_resolves_the_push_credential(client, prepared_db):
    """The shared resolver (integrations/hosts.py): the right kind, the right
    credential shape, and None for GitHub or unconnected hosts."""
    import uuid as _uuid

    from engine.db.session import session_scope
    from engine.integrations.hosts import host_connection, push_credential

    user = f"host_{_uuid.uuid4().hex[:8]}"
    await client.put(
        "/v1/integrations/bitbucket",
        json={"config": {"username": "dev-user", "app_password": "ATBB-secret"}},
        headers=auth_headers(user),
    )

    async with session_scope() as db:
        host = await host_connection(db, user, "https://bitbucket.org/acme/demo")
        assert host is not None and host[0] == "bitbucket"
        assert push_credential(host) == ("dev-user", "ATBB-secret")

        assert await host_connection(db, user, "https://github.com/acme/demo") is None
        assert await host_connection(db, user, "https://gitlab.com/acme/demo") is None
        assert push_credential(None) is None


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
