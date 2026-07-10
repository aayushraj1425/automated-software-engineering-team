"""Background task: review a webhook'd pull request and comment on it.

Fetch the pull request's diff, run the diff-based Reviewer, and post the
findings as one review comment. Runs off the request path (queued by
engine/api/webhooks.py) so the webhook itself returns immediately. Errors are
logged, never raised into the background runner. Design note:
docs/architecture/WEBHOOK_REVIEWER.md.
"""

import structlog

from engine.agents.pr_reviewer import render_review_comment, review_diff
from engine.github import (
    GitHubApiError,
    fetch_pull_request_diff,
    post_pull_request_review,
)

log = structlog.get_logger(__name__)


async def review_pull_request(owner: str, repo: str, number: int) -> None:
    """Fetch → review → comment. Swallows and logs failures (background task)."""
    slug = f"{owner}/{repo}#{number}"
    try:
        diff = await fetch_pull_request_diff(owner, repo, number)
        review = await review_diff(diff)
        body = render_review_comment(review)
        url = await post_pull_request_review(owner, repo, number, body)
        log.info("webhook.reviewed", pr=slug, findings=len(review["findings"]), comment_url=url)
    except GitHubApiError as exc:
        log.warning("webhook.review_failed", pr=slug, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — a background task must not crash the worker
        log.error("webhook.review_error", pr=slug, error=str(exc))
