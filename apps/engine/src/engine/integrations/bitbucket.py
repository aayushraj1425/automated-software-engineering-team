"""Bitbucket adapter: recognize a Bitbucket repository and open a pull request.

The third source host, behind the same seam GitLab cut: a pure "open this
there" function that never touches the database or a run. Auth is Bitbucket
Cloud's app passwords (HTTP Basic: username + app password). In dry-run mode
(INTEGRATIONS_DRY_RUN=1: tests, offline dev) it skips the network and returns
a deterministic placeholder, so the publish path runs offline.
Design note: docs/architecture/SOURCE_HOSTS.md.
"""

import re

import httpx
import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)

API_URL = "https://api.bitbucket.org/2.0"
_TIMEOUT_SECONDS = 30

# bitbucket.org/workspace/repo — exactly two segments, paths never nest.
_BITBUCKET_URL = re.compile(r"bitbucket\.org[:/](?P<path>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")


class PullRequestError(Exception):
    """The pull request could not be created; the message is safe to show."""


def parse_bitbucket_repo(url: str) -> str | None:
    """The "workspace/repo" path for a bitbucket.org URL; None otherwise."""
    match = _BITBUCKET_URL.search(url.strip())
    return match.group("path") if match else None


async def open_pull_request(
    config: dict,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    title: str,
    body: str,
) -> str:
    """Create a pull request and return its web URL."""
    path = parse_bitbucket_repo(repo_url)
    if path is None:
        raise PullRequestError(f"not a Bitbucket repository URL: {repo_url}")
    if get_settings().integrations_dry_run:
        return f"https://bitbucket.org/{path}/pull-requests/dry-run"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{API_URL}/repositories/{path}/pullrequests",
                auth=(config["username"], config["app_password"]),
                json={
                    "title": title,
                    "description": body,
                    "source": {"branch": {"name": source_branch}},
                    "destination": {"branch": {"name": target_branch}},
                },
            )
    except httpx.HTTPError as exc:
        raise PullRequestError(f"could not reach Bitbucket: {exc}") from exc
    if response.status_code not in (200, 201):
        raise PullRequestError(f"Bitbucket refused the pull request: {_refusal_detail(response)}")
    url = str(response.json().get("links", {}).get("html", {}).get("href", ""))
    log.info("pr.opened", repository=path, branch=source_branch, url=url)
    return url


def _refusal_detail(response: httpx.Response) -> str:
    """Bitbucket's error message when it sent JSON; the raw body tail otherwise."""
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return response.text[:200]
