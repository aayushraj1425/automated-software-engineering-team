"""GitHub REST API: open a run's pull request, and (for the webhook reviewer)
read a pull request's diff and post a review comment.

Authentication is a personal access token from the environment for now; per-user
encrypted tokens are the Identity & Keys workstream. Webhook payloads are
authenticated separately, by HMAC signature (see verify_webhook_signature).
"""

import hashlib
import hmac
import re

import httpx
import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)

API_BASE = "https://api.github.com"

_GITHUB_URL = re.compile(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$")


class PullRequestError(Exception):
    """The pull request could not be created; the message is safe to show."""


class GitHubApiError(Exception):
    """A GitHub read/write the webhook reviewer needs failed; message is safe."""


def _refusal_detail(response: httpx.Response) -> str:
    """GitHub's error message when it sent JSON; the raw body tail otherwise.
    (A proxy's HTML error page must not crash the error path itself.)"""
    try:
        data = response.json()
    except ValueError:
        data = None
    message = data.get("message") if isinstance(data, dict) else None
    return str(message) if message else response.text[:200]


def verify_webhook_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """True when X-Hub-Signature-256 matches an HMAC-SHA256 of the raw body.

    Fail closed: an empty secret, a missing header, or a malformed header is
    never a match. The comparison is constant-time (hmac.compare_digest) so the
    secret cannot be recovered by timing the response.
    """
    if not secret or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    sent = signature_header[len(prefix) :]
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, expected)


async def fetch_pull_request_diff(owner: str, repo: str, number: int) -> str:
    """The unified diff of a pull request (the `application/vnd.github.diff` media type)."""
    token = get_settings().github_token
    if not token:
        raise GitHubApiError("GITHUB_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.diff",
            },
        )
    if response.status_code != 200:
        raise GitHubApiError(f"could not fetch PR #{number} diff (HTTP {response.status_code})")
    return response.text


async def post_pull_request_review(owner: str, repo: str, number: int, body: str) -> str:
    """Post a single review comment on a pull request; return its API URL.

    The review uses event COMMENT (neither approve nor request-changes) with a
    markdown body — reliable, unlike position-mapped inline comments.
    """
    token = get_settings().github_token
    if not token:
        raise GitHubApiError("GITHUB_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{API_BASE}/repos/{owner}/{repo}/pulls/{number}/reviews",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"event": "COMMENT", "body": body},
        )
    if response.status_code not in (200, 201):
        raise GitHubApiError(f"GitHub refused the review comment: {_refusal_detail(response)}")
    url = response.json().get("html_url", "")
    log.info("pr.reviewed", repo=f"{owner}/{repo}", number=number, url=url)
    return url


def parse_github_repo(url: str) -> tuple[str, str] | None:
    """(owner, repo) for a GitHub URL; None for anything else (e.g. local paths)."""
    match = _GITHUB_URL.search(url.strip())
    if match is None:
        return None
    return match.group("owner"), match.group("repo")


async def open_pull_request(
    repo_url: str, branch: str, base_branch: str, title: str, body: str
) -> str:
    """Create the pull request and return its URL."""
    parsed = parse_github_repo(repo_url)
    if parsed is None:
        raise PullRequestError(f"not a GitHub repository URL: {repo_url}")
    token = get_settings().github_token
    if not token:
        raise PullRequestError("GITHUB_TOKEN is not configured")

    owner, repo = parsed
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{API_BASE}/repos/{owner}/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "head": branch, "base": base_branch, "body": body},
        )
    if response.status_code != 201:
        raise PullRequestError(f"GitHub refused the pull request: {_refusal_detail(response)}")
    url = response.json()["html_url"]
    log.info("pr.opened", repo=f"{owner}/{repo}", branch=branch, url=url)
    return url
