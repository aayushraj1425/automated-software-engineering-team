"""Kubeconfig validation: accept only what cannot run code or read host files.

A kubeconfig is not just data. `exec` and `auth-provider` run a local program,
`*-file` fields read host files, and `proxy-url` reroutes traffic. We therefore
never use the caller's file: we pick one context and build a brand new minimal
kubeconfig from an allow-list of inline fields. Errors name fields, never values.
"""

import fnmatch
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import yaml

from engine.deploy.safety import PreviewError

MAX_KUBECONFIG_BYTES = 64_000

_FORBIDDEN_KEYS = frozenset(
    {
        "exec",
        "auth-provider",
        "authprovider",
        "tokenfile",
        "token-file",
        "certificate-authority",
        "client-certificate",
        "client-key",
        "proxy-url",
        "insecure-skip-tls-verify",
        "as",
        "as-uid",
        "as-groups",
        "as-user-extra",
        "username",
        "password",
        "disable-compression",
    }
)
_CLUSTER_KEYS = frozenset({"server", "certificate-authority-data", "tls-server-name"})
_USER_KEYS = frozenset({"token", "client-certificate-data", "client-key-data"})
_PRODUCTION = re.compile(r"(^|[^a-z0-9])(prod|production|prd|live)([^a-z0-9]|$)")
_BLOCKED_HOSTS = frozenset({"metadata.google.internal", "metadata", "kubernetes.docker.internal"})


@dataclass(frozen=True)
class SafeKubeconfig:
    """A rebuilt kubeconfig plus the secret strings to scrub from CLI output."""

    text: str
    server_host: str
    secrets: tuple[str, ...]


def _mapping(value: object, what: str) -> dict:
    if not isinstance(value, dict):
        raise PreviewError(f"kubeconfig: {what} must be a mapping")
    return value


def _named(items: object, what: str) -> dict[str, dict]:
    if not isinstance(items, list) or not items:
        raise PreviewError(f"kubeconfig: {what} list is missing")
    out: dict[str, dict] = {}
    for item in items:
        entry = _mapping(item, what)
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise PreviewError(f"kubeconfig: a {what} entry has no name")
        out[name] = entry
    return out


def _reject_forbidden(section: dict, where: str) -> None:
    for key in section:
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_KEYS:
            raise PreviewError(
                f"kubeconfig: '{lowered}' in {where} is not allowed "
                "(exec, auth-provider, file references, proxies and TLS skipping are blocked)"
            )


def _check_server(server: str, allow_local: bool, allowed_hosts: list[str]) -> str:
    parts = urlsplit(server)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise PreviewError("kubeconfig: the cluster server must be an https URL")
    if parts.username or parts.password:
        raise PreviewError("kubeconfig: the cluster server URL must not embed credentials")
    if host in _BLOCKED_HOSTS or host.endswith(".internal"):
        raise PreviewError("kubeconfig: that cluster server address is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_link_local or address.is_unspecified or address.is_multicast
    ):
        raise PreviewError("kubeconfig: that cluster server address is not allowed")
    loopback = host == "localhost" or (address is not None and address.is_loopback)
    if loopback and not allow_local:
        raise PreviewError(
            "kubeconfig: a loopback cluster server is only allowed with PREVIEW_ALLOW_LOCAL_CLUSTER"
        )
    if allowed_hosts and not any(fnmatch.fnmatchcase(host, p.lower()) for p in allowed_hosts):
        raise PreviewError("kubeconfig: the cluster server host is not in the allowed list")
    return host


def _looks_like_production(*names: str) -> bool:
    return any(_PRODUCTION.search(name.lower()) for name in names if name)


def sanitize_kubeconfig(
    raw: str,
    *,
    allow_local_cluster: bool = False,
    allowed_api_hosts: list[str] | None = None,
) -> SafeKubeconfig:
    """Validate `raw` and return a rebuilt single-context kubeconfig."""
    if not isinstance(raw, str) or not raw.strip():
        raise PreviewError("kubeconfig credential is missing")
    if len(raw.encode("utf-8")) > MAX_KUBECONFIG_BYTES:
        raise PreviewError("kubeconfig is too large")
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        # The parser's message can quote the offending text, so it is dropped.
        raise PreviewError("kubeconfig is not valid YAML") from None
    doc = _mapping(loaded, "the document")

    clusters = _named(doc.get("clusters"), "clusters")
    users = _named(doc.get("users"), "users")
    contexts = _named(doc.get("contexts"), "contexts")
    current = doc.get("current-context")
    if not isinstance(current, str) or current not in contexts:
        if len(contexts) != 1:
            raise PreviewError("kubeconfig: set current-context to the preview cluster context")
        current = next(iter(contexts))

    ctx = _mapping(contexts[current].get("context"), "the context")
    _reject_forbidden(ctx, "the context")
    cluster_name, user_name = ctx.get("cluster"), ctx.get("user")
    if cluster_name not in clusters or user_name not in users:
        raise PreviewError("kubeconfig: the context points at a missing cluster or user")

    cluster = _mapping(clusters[cluster_name].get("cluster"), "the cluster")
    user = _mapping(users[user_name].get("user"), "the user")
    _reject_forbidden(cluster, "the cluster")
    _reject_forbidden(user, "the user")
    for key in cluster:
        if key not in _CLUSTER_KEYS:
            raise PreviewError("kubeconfig: the cluster entry has an unsupported field")
    for key in user:
        if key not in _USER_KEYS:
            raise PreviewError("kubeconfig: the user entry has an unsupported field")

    server = cluster.get("server")
    if not isinstance(server, str):
        raise PreviewError("kubeconfig: the cluster has no server")
    host = _check_server(server, allow_local_cluster, allowed_api_hosts or [])
    if _looks_like_production(str(current), str(cluster_name), str(user_name), host):
        raise PreviewError("kubeconfig: production-looking cluster names are refused")

    token = user.get("token")
    cert, key = user.get("client-certificate-data"), user.get("client-key-data")
    ca = cluster.get("certificate-authority-data")
    if not token and not (cert and key):
        raise PreviewError("kubeconfig: the user needs an inline token or client certificate")
    for value in (token, cert, key, ca):
        if value is not None and not isinstance(value, str):
            raise PreviewError("kubeconfig: credential fields must be strings")

    safe_cluster: dict[str, object] = {"server": server}
    for field in ("certificate-authority-data", "tls-server-name"):
        if cluster.get(field):
            safe_cluster[field] = cluster[field]
    safe_user = {k: user[k] for k in _USER_KEYS if user.get(k)}
    rebuilt = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": "asep-preview",
        "clusters": [{"name": "asep-preview", "cluster": safe_cluster}],
        "users": [{"name": "asep-preview", "user": safe_user}],
        "contexts": [
            {"name": "asep-preview", "context": {"cluster": "asep-preview", "user": "asep-preview"}}
        ],
    }
    secrets = tuple(str(v) for v in (token, cert, key, ca) if v)
    return SafeKubeconfig(text=yaml.safe_dump(rebuilt), server_host=host, secrets=secrets)
