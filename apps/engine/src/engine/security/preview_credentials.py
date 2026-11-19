"""Encrypted preview-only credentials, separate from provider keys and prompts."""

import json
from urllib.parse import urlsplit

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import PreviewCredential
from engine.security.crypto import DecryptionError, decrypt

_FORBIDDEN = {
    "exec",
    "auth-provider",
    "tokenFile",
    "token-file",
    "client-certificate",
    "client-key",
    "certificate-authority",
    "proxy-url",
}


def validate_kubeconfig(raw: str) -> None:
    """Accept self-contained kubeconfigs without executing plugins or reading files."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise ValueError("Invalid kubeconfig document") from None
    if not isinstance(data, dict) or data.get("kind") != "Config" or data.get("apiVersion") != "v1":
        raise ValueError("Expected a Kubernetes v1 Config")
    if not all(
        isinstance(data.get(key), list) and data[key] for key in ("clusters", "users", "contexts")
    ):
        raise ValueError("Kubeconfig needs clusters, users and contexts")
    current = data.get("current-context")
    if not isinstance(current, str) or not current:
        raise ValueError("Kubeconfig needs an explicit current context")
    contexts = [c for c in data["contexts"] if isinstance(c, dict) and c.get("name") == current]
    if len(contexts) != 1:
        raise ValueError("Kubeconfig needs one valid current context")
    if any(
        word in str(current).lower().replace("_", "-").split("-") for word in ("prod", "production")
    ):
        raise ValueError("Production contexts cannot be used for previews")
    stack = [data]
    seen: set[int] = set()
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, dict):
            if _FORBIDDEN.intersection(item):
                raise ValueError(
                    "Kubeconfig plugins, external credential files and proxies are forbidden"
                )
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    for entry in data["clusters"]:
        cluster = entry.get("cluster") if isinstance(entry, dict) else None
        if not isinstance(cluster, dict):
            raise ValueError("Invalid cluster configuration")
        server = cluster.get("server")
        if not isinstance(server, str):
            raise ValueError("Cluster server must be an HTTPS URL")
        parsed = urlsplit(server)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Cluster server must be an HTTPS URL without embedded credentials")


async def load_preview_credentials(db: AsyncSession, org_id: str | None) -> dict[str, str]:
    if org_id is None:
        raise ValueError("An organization preview credential is required")
    row = await db.get(PreviewCredential, org_id)
    if row is None:
        raise ValueError("No preview credential is configured for this organization")
    try:
        data = json.loads(decrypt(row.encrypted_credentials))
        if not isinstance(data, dict) or not isinstance(data.get("kubeconfig"), str):
            raise ValueError("Invalid stored preview credential")
        validate_kubeconfig(data["kubeconfig"])
        return {"kubeconfig": data["kubeconfig"]}
    except (DecryptionError, ValueError, TypeError):
        raise ValueError("Stored preview credential is invalid or cannot be decrypted") from None
