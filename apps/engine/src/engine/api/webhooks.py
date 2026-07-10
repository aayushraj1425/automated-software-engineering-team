"""GitHub webhook receiver: authenticate by HMAC signature, queue a review.

This is the one /v1/* route that does not carry the BFF service JWT — GitHub
calls it directly, so it is authenticated by the webhook signature instead
(see docs/architecture/WEBHOOK_REVIEWER.md). It stays thin: verify, parse,
queue a background review, and return 202 well inside GitHub's delivery timeout.
"""

import json

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from engine.agents.webhook_review import review_pull_request
from engine.config import get_settings
from engine.github import verify_webhook_signature

log = structlog.get_logger(__name__)

router = APIRouter()

# Pull-request actions worth a fresh review: a new PR, a reopened one, or new
# commits pushed to it. Everything else (labels, assignments, closes) is ignored.
_REVIEWABLE_ACTIONS = {"opened", "reopened", "synchronize"}


@router.post("/v1/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    secret = get_settings().github_webhook_secret
    if not verify_webhook_signature(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event {x_github_event!r} is not reviewed"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Body is not valid JSON") from None

    action = payload.get("action")
    if action not in _REVIEWABLE_ACTIONS:
        return {"status": "ignored", "reason": f"action {action!r} needs no review"}

    coords = _pull_request_coords(payload)
    if coords is None:
        raise HTTPException(status_code=400, detail="Malformed pull_request payload")
    owner, repo, number = coords

    background.add_task(review_pull_request, owner, repo, number)
    log.info("webhook.queued", pr=f"{owner}/{repo}#{number}", action=action)
    return {"status": "queued", "pull_request": f"{owner}/{repo}#{number}"}


def _pull_request_coords(payload: dict) -> tuple[str, str, int] | None:
    """(owner, repo, number) from a pull_request webhook payload, or None."""
    pull_request = payload.get("pull_request")
    repository = payload.get("repository")
    if not isinstance(pull_request, dict) or not isinstance(repository, dict):
        return None
    number = pull_request.get("number")
    full_name = repository.get("full_name", "")
    if not isinstance(number, int) or "/" not in full_name:
        return None
    owner, repo = full_name.split("/", 1)
    if not owner or not repo:
        return None
    return owner, repo, number
