"""Opens the pull request for a finished run (GitHub REST API).

The only GitHub write the engine performs: after the Reviewer approves and
the run branch is pushed, one POST creates the pull request. Authentication
is a personal access token from the environment for now; per-user encrypted
tokens are the Identity & Keys workstream.
"""

import re

import httpx
import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)

API_BASE = "https://api.github.com"

_GITHUB_URL = re.compile(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$")


class PullRequestError(Exception):
    """The pull request could not be created; the message is safe to show."""


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
        detail = response.json().get("message", response.text[:200])
        raise PullRequestError(f"GitHub refused the pull request: {detail}")
    url = response.json()["html_url"]
    log.info("pr.opened", repo=f"{owner}/{repo}", branch=branch, url=url)
    return url
