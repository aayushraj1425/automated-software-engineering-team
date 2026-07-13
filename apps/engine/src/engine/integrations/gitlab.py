"""GitLab adapter: recognize a GitLab repository and open a merge request.

A pure "open this there" function — it never touches the database or a run. In
dry-run mode (INTEGRATIONS_DRY_RUN=1: tests, offline dev) it skips the network
and returns a deterministic placeholder, so the publish path runs offline.
Design note: docs/architecture/SOURCE_HOSTS.md.
"""

import re
from urllib.parse import quote

import httpx
import structlog

from engine.config import get_settings

log = structlog.get_logger(__name__)

DEFAULT_BASE_URL = "https://gitlab.com"
_TIMEOUT_SECONDS = 30

# gitlab.com/group/repo or gitlab.com/group/subgroup/repo (project path may nest).
_GITLAB_URL = re.compile(r"gitlab\.com[:/](?P<path>[^\s]+?)(?:\.git)?/?$")


class MergeRequestError(Exception):
    """The merge request could not be created; the message is safe to show."""


def parse_gitlab_repo(url: str) -> str | None:
    """The project path (e.g. "group/repo") for a gitlab.com URL; None otherwise."""
    match = _GITLAB_URL.search(url.strip())
    return match.group("path") if match else None


async def open_merge_request(
    config: dict,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    title: str,
    body: str,
) -> str:
    """Create a merge request and return its web URL."""
    project_path = parse_gitlab_repo(repo_url)
    if project_path is None:
        raise MergeRequestError(f"not a GitLab repository URL: {repo_url}")
    base_url = config.get("base_url", DEFAULT_BASE_URL)
    if get_settings().integrations_dry_run:
        return f"{base_url}/{project_path}/-/merge_requests/dry-run"

    encoded = quote(project_path, safe="")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/api/v4/projects/{encoded}/merge_requests",
                headers={"PRIVATE-TOKEN": config["token"]},
                json={
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": body,
                },
            )
    except httpx.HTTPError as exc:
        raise MergeRequestError(f"could not reach GitLab: {exc}") from exc
    if response.status_code not in (200, 201):
        raise MergeRequestError(f"GitLab refused the merge request: {_refusal_detail(response)}")
    url = response.json().get("web_url", "")
    log.info("mr.opened", project=project_path, branch=source_branch, url=url)
    return url


def _refusal_detail(response: httpx.Response) -> str:
    """GitLab's error message when it sent JSON; the raw body tail otherwise."""
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    message = data.get("message") or data.get("error") if isinstance(data, dict) else None
    return str(message) if message else response.text[:200]
