"""Bounded, network-safe HTTP smoke checks against a preview URL.

The chart (untrusted) chooses the ingress host, so the URL is not trusted
either. Every address the host resolves to must be public, the connection is
pinned to the address we validated (DNS rebinding cannot swap it), redirects are
followed only within the same host, and every limit below is a hard cap.
"""

import asyncio
import ipaddress
import re
import socket
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from engine.deploy.contracts import SmokeResult
from engine.deploy.safety import PreviewError, scrub

MAX_PATHS = 10
MAX_BODY_BYTES = 64_000
MAX_REDIRECTS = 3
MIN_TIMEOUT, MAX_TIMEOUT = 1, 120
PER_REQUEST_TIMEOUT = 10.0
RETRY_INTERVAL = 2.0
MAX_ATTEMPTS = 15
_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/\-]*(\?[A-Za-z0-9._~!$&'()*+,;=:@%/?\-]*)?$")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class Blocked(PreviewError):
    """A safety rule refused the request. Retrying cannot make it acceptable."""


async def resolve_host(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return sorted({str(info[4][0]) for info in infos})


def validate_paths(paths: list[str]) -> list[str]:
    if not paths or len(paths) > MAX_PATHS:
        raise PreviewError(f"smoke tests need between 1 and {MAX_PATHS} paths")
    for path in paths:
        if len(path) > 200 or path.startswith("//") or not _PATH.match(path):
            raise PreviewError("a smoke test path is not a plain absolute path")
    return paths


def check_address(address: str, *, allow_private: bool, allow_local: bool) -> None:
    ip = ipaddress.ip_address(address)
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        raise Blocked("the preview host resolves to a blocked address")
    if ip.is_loopback:
        if not allow_local:
            raise Blocked("the preview host resolves to a loopback address")
        return
    if not ip.is_global and not allow_private:
        raise Blocked("the preview host resolves to a private address")


def _origin(url: str) -> tuple[str, str, int, str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise PreviewError("the preview URL must be http or https")
    if parts.username or parts.password:
        raise PreviewError("the preview URL must not embed credentials")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise PreviewError("the preview URL has an invalid port") from None
    return parts.scheme, host, port, parts.path.rstrip("/")


def _pinned_url(scheme: str, address: str, port: int, path: str) -> str:
    shown = f"[{address}]" if ":" in address else address
    return f"{scheme}://{shown}:{port}{path}"


async def _fetch_once(
    client: httpx.AsyncClient,
    url: str,
    *,
    resolver: Resolver,
    allow_private: bool,
    allow_local: bool,
    timeout: float,
) -> tuple[int, int, str]:
    """GET `url` with pinning and same-host redirects. Returns (status, bytes, content type)."""
    scheme, host, port, _ = _origin(url)
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        scheme, hop_host, hop_port, _ = _origin(current)
        if hop_host != host:
            raise Blocked("the preview redirected to a different host")
        addresses = await resolver(hop_host, hop_port)
        if not addresses:
            raise PreviewError("the preview host did not resolve")
        for address in addresses:
            check_address(address, allow_private=allow_private, allow_local=allow_local)
        parts = urlsplit(current)
        target = parts.path or "/"
        if parts.query:
            target += f"?{parts.query}"
        default_port = 443 if scheme == "https" else 80
        host_header = hop_host if hop_port == default_port else f"{hop_host}:{hop_port}"
        async with client.stream(
            "GET",
            _pinned_url(scheme, addresses[0], hop_port, target),
            headers={"Host": host_header, "User-Agent": "asep-preview-smoke/1"},
            extensions={"sni_hostname": hop_host},
            timeout=timeout,
        ) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    return response.status_code, 0, ""
                current = urljoin(current, location)
                continue
            read = 0
            async for chunk in response.aiter_bytes():
                read += len(chunk)
                if read >= MAX_BODY_BYTES:
                    break
            return (
                response.status_code,
                min(read, MAX_BODY_BYTES),
                response.headers.get("content-type", "")[:80],
            )
    raise Blocked("too many redirects")


async def run_smoke(
    url: str,
    paths: list[str],
    timeout_seconds: int,
    *,
    allow_private: bool = False,
    allow_local: bool = False,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SmokeResult:
    """Check each path returns 2xx, retrying until its share of the deadline."""
    try:
        scheme, host, port, base_path = _origin(url)
        validate_paths(paths)
    except PreviewError as exc:
        return SmokeResult(passed=False, checks=[], error=str(exc))
    budget = float(min(max(timeout_seconds, MIN_TIMEOUT), MAX_TIMEOUT))
    deadline = time.monotonic() + budget
    resolve = resolver or resolve_host
    checks: list[dict] = []

    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        for index, path in enumerate(paths):
            remaining = max(deadline - time.monotonic(), 0.0)
            path_deadline = time.monotonic() + remaining / (len(paths) - index)
            full = f"{scheme}://{host}:{port}{base_path}{path}"
            started = time.monotonic()
            attempts = 0
            status: int | None = None
            size = 0
            ctype = ""
            error: str | None = None
            while True:
                attempts += 1
                left = max(path_deadline - time.monotonic(), 0.5)
                try:
                    status, size, ctype = await _fetch_once(
                        client,
                        full,
                        resolver=resolve,
                        allow_private=allow_private,
                        allow_local=allow_local,
                        timeout=min(PER_REQUEST_TIMEOUT, left),
                    )
                    error = None if 200 <= status < 300 else f"unexpected status {status}"
                except Blocked as exc:
                    status, error = None, str(exc)
                    break
                except PreviewError as exc:
                    status, error = None, str(exc)
                except httpx.HTTPError as exc:
                    status, error = None, scrub(f"{type(exc).__name__}", limit=200)
                if (
                    error is None
                    or attempts >= MAX_ATTEMPTS
                    or time.monotonic() + RETRY_INTERVAL >= path_deadline
                ):
                    break
                await sleep(RETRY_INTERVAL)
            checks.append(
                {
                    "path": path,
                    "status": status,
                    "ok": error is None,
                    "attempts": attempts,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "bytes": size,
                    "content_type": ctype,
                    "error": error,
                }
            )

    failed = [c for c in checks if not c["ok"]]
    return SmokeResult(
        passed=not failed,
        checks=checks,
        error=None if not failed else f"{len(failed)} of {len(checks)} checks failed",
    )
