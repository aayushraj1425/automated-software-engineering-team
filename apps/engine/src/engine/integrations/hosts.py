"""Which host, whose credential — shared by publish and the manual push.

A repository URL maps to at most one connected host kind (GitLab or
Bitbucket); GitHub keeps using the environment token and local/unknown URLs
push plainly, so neither appears here. Design note:
docs/architecture/SOURCE_HOSTS.md.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.enums import IntegrationKind
from engine.integrations import bitbucket, gitlab
from engine.integrations.connections import load_config


async def host_connection(
    db: AsyncSession, user_id: str, repo_url: str
) -> tuple[str, dict[str, Any]] | None:
    """(kind, decrypted config) for the repository's host, when the user has
    one connected — None for GitHub, local paths, and unconnected hosts.

    A URL on no SaaS host may still be the user's *self-hosted* GitLab: the
    connection's base_url names the instance, so the config is loaded and
    asked (connection_repo_path). Self-hosted Bitbucket stays out — its
    Server/Data Center API is a different protocol, not a different host."""
    if gitlab.parse_gitlab_repo(repo_url) is not None:
        config = await load_config(db, user_id, IntegrationKind.GITLAB)
        if config:
            return (IntegrationKind.GITLAB, config)
        return None
    if bitbucket.parse_bitbucket_repo(repo_url) is not None:
        config = await load_config(db, user_id, IntegrationKind.BITBUCKET)
        if config:
            return (IntegrationKind.BITBUCKET, config)
        return None
    if repo_url.strip().lower().startswith(("https://", "git@")) and "github.com" not in repo_url:
        config = await load_config(db, user_id, IntegrationKind.GITLAB)
        if config and gitlab.connection_repo_path(config, repo_url) is not None:
            return (IntegrationKind.GITLAB, config)
    return None


def push_credential(host: tuple[str, dict[str, Any]] | None) -> tuple[str, str] | None:
    """The `(userinfo, secret)` pair authenticating the https push
    (workspace.manager.push_branch), or None for the default behavior."""
    if host is None:
        return None
    kind, config = host
    if kind == IntegrationKind.GITLAB:
        return ("oauth2", config["token"])
    return (config["username"], config["app_password"])
