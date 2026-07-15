"""The GitHub webhook endpoint: authenticate, route the event, queue a review.

The client fixture's ASGI transport waits for FastAPI background tasks, so a
queued review has already run by the time the POST returns — we monkeypatch the
review orchestrator to record the call instead of hitting GitHub. Design note:
docs/architecture/WEBHOOK_REVIEWER.md.
"""

import hashlib
import hmac
import json

import pytest

from engine.agents import webhook_review
from engine.api import webhooks
from engine.config import get_settings

_SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def configure_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "github_webhook_secret", _SECRET)
    webhooks._queued_deliveries.clear()  # each test starts with no remembered ids


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _pr_payload(action="opened", number=7, full_name="acme/demo") -> bytes:
    return json.dumps(
        {
            "action": action,
            "pull_request": {"number": number},
            "repository": {"full_name": full_name},
        }
    ).encode()


def _capture_reviews(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake(owner, repo, number):
        calls.append((owner, repo, number))

    # The endpoint calls the name imported into its own module namespace.
    monkeypatch.setattr(webhooks, "review_pull_request", fake)
    return calls


async def _post(client, body: bytes, event="pull_request", signature=None, delivery=""):
    headers = {"X-GitHub-Event": event}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    if delivery:
        headers["X-GitHub-Delivery"] = delivery
    return await client.post("/v1/webhooks/github", content=body, headers=headers)


async def test_opened_pull_request_queues_a_review(client, monkeypatch):
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload(action="opened", number=42)

    resp = await _post(client, body, signature=_sign(body))

    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "queued"
    assert calls == [("acme", "demo", 42)]


async def test_a_bad_signature_is_401_and_queues_nothing(client, monkeypatch):
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload()

    resp = await _post(client, body, signature="sha256=deadbeef")

    assert resp.status_code == 401
    assert calls == []


async def test_a_missing_signature_is_401(client, monkeypatch):
    _capture_reviews(monkeypatch)
    body = _pr_payload()
    resp = await _post(client, body, signature=None)
    assert resp.status_code == 401


async def test_an_unconfigured_secret_rejects_everything(client, monkeypatch):
    calls = _capture_reviews(monkeypatch)
    monkeypatch.setattr(get_settings(), "github_webhook_secret", "")
    body = _pr_payload()
    # Even a signature computed against an empty secret must not authenticate.
    resp = await _post(client, body, signature=_sign(body))
    assert resp.status_code == 401
    assert calls == []


async def test_a_non_pull_request_event_is_ignored(client, monkeypatch):
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload()
    resp = await _post(client, body, event="push", signature=_sign(body))
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
    assert calls == []


async def test_a_non_reviewable_action_is_ignored(client, monkeypatch):
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload(action="labeled")
    resp = await _post(client, body, signature=_sign(body))
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
    assert calls == []


async def test_a_malformed_pull_request_payload_is_400(client, monkeypatch):
    _capture_reviews(monkeypatch)
    body = json.dumps({"action": "opened", "repository": {}}).encode()  # no pull_request
    resp = await _post(client, body, signature=_sign(body))
    assert resp.status_code == 400


async def test_a_redelivered_delivery_id_is_not_reviewed_twice(client, monkeypatch):
    """GitHub retries carry the same X-GitHub-Delivery id (audit finding 3)."""
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload(number=42)

    first = await _post(client, body, signature=_sign(body), delivery="dedupe-1")
    second = await _post(client, body, signature=_sign(body), delivery="dedupe-1")

    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "ignored"
    assert calls == [("acme", "demo", 42)]  # exactly one review


async def test_distinct_delivery_ids_each_get_a_review(client, monkeypatch):
    """New pushes arrive as new deliveries and must still be reviewed."""
    calls = _capture_reviews(monkeypatch)
    body = _pr_payload(number=42, action="synchronize")

    await _post(client, body, signature=_sign(body), delivery="push-1")
    await _post(client, body, signature=_sign(body), delivery="push-2")

    assert calls == [("acme", "demo", 42), ("acme", "demo", 42)]


async def test_the_orchestrator_fetches_reviews_and_posts(monkeypatch):
    """review_pull_request wires the diff fetch, the reviewer, and the comment."""
    posted: dict = {}

    async def fake_fetch(owner, repo, number):
        return "diff --git a/x b/x\n+bug\n"

    async def fake_post(owner, repo, number, body):
        posted["body"] = body
        posted["pr"] = (owner, repo, number)
        return "https://github.com/acme/demo/pull/7#pullrequestreview-1"

    monkeypatch.setattr(webhook_review, "fetch_pull_request_diff", fake_fetch)
    monkeypatch.setattr(webhook_review, "post_pull_request_review", fake_post)

    await webhook_review.review_pull_request("acme", "demo", 7)

    assert posted["pr"] == ("acme", "demo", 7)
    assert "ASEP automated review" in posted["body"]  # the rendered comment was posted
