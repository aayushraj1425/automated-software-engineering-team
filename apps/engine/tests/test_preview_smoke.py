"""Preview adapter: bounded, network-safe smoke checks (mocked HTTP, no network)."""

import httpx
import pytest

from engine.deploy import preview, smoke
from engine.deploy.contracts import PreviewOptions

PUBLIC = "93.184.216.34"


async def no_sleep(_seconds: float) -> None:
    return None


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return mapping.get(host, [])

    return resolve


async def run(handler, url="https://preview.example.com", paths=("/healthz",), **kw):
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    result = await smoke.run_smoke(
        url,
        list(paths),
        kw.pop("timeout_seconds", 30),
        resolver=kw.pop("resolver", resolver_for({"preview.example.com": [PUBLIC]})),
        transport=httpx.MockTransport(wrapped),
        sleep=no_sleep,
        **kw,
    )
    return result, seen


async def test_passing_check_is_pinned_to_the_validated_address():
    result, seen = await run(
        lambda r: httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
    )
    assert result.passed and result.error is None
    check = result.checks[0]
    assert check["path"] == "/healthz" and check["status"] == 200 and check["ok"]
    assert check["bytes"] == 2 and check["content_type"] == "text/plain"
    request = seen[0]
    assert request.url.host == PUBLIC  # connection goes to the address we validated
    assert request.headers["host"] == "preview.example.com"
    assert request.extensions["sni_hostname"] == "preview.example.com"
    assert request.url.path == "/healthz"


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "192.168.1.9",
        "172.16.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd00::1",
    ],
)
async def test_non_public_addresses_are_blocked(address):
    result, seen = await run(
        lambda r: httpx.Response(200), resolver=resolver_for({"preview.example.com": [address]})
    )
    assert not result.passed and seen == []
    assert "address" in result.checks[0]["error"]


async def test_one_private_address_among_public_ones_blocks_the_host():
    result, seen = await run(
        lambda r: httpx.Response(200),
        resolver=resolver_for({"preview.example.com": [PUBLIC, "10.0.0.5"]}),
    )
    assert not result.passed and seen == []


async def test_private_addresses_need_explicit_opt_in_but_link_local_never_passes():
    private = resolver_for({"preview.example.com": ["10.0.0.5"]})
    result, _ = await run(lambda r: httpx.Response(200), resolver=private, allow_private=True)
    assert result.passed
    metadata = resolver_for({"preview.example.com": ["169.254.169.254"]})
    result, seen = await run(
        lambda r: httpx.Response(200), resolver=metadata, allow_private=True, allow_local=True
    )
    assert not result.passed and seen == []


async def test_loopback_only_with_local_opt_in():
    loop = resolver_for({"preview.example.com": ["127.0.0.1"]})
    result, _ = await run(lambda r: httpx.Response(200), resolver=loop, allow_local=True)
    assert result.passed


async def test_same_host_redirect_is_followed_and_cross_host_is_refused():
    def to_https(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(301, headers={"location": "/ready"})
        return httpx.Response(200, text="ready")

    result, seen = await run(to_https)
    assert result.passed and [r.url.path for r in seen] == ["/healthz", "/ready"]

    def elsewhere(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    result, seen = await run(elsewhere)
    assert not result.passed and "different host" in result.checks[0]["error"]
    assert len(seen) == 1


async def test_redirect_loops_are_bounded():
    result, seen = await run(lambda r: httpx.Response(302, headers={"location": "/healthz"}))
    assert not result.passed
    assert len(seen) <= smoke.MAX_ATTEMPTS * (smoke.MAX_REDIRECTS + 1)


async def test_not_ready_then_ready_retries():
    answers = iter([503, 503, 200])
    result, seen = await run(lambda r: httpx.Response(next(answers)))
    assert result.passed and result.checks[0]["attempts"] == 3 and len(seen) == 3


async def test_persistent_failure_is_bounded_and_reported():
    result, seen = await run(lambda r: httpx.Response(500), paths=["/a", "/b"])
    assert not result.passed and result.error == "2 of 2 checks failed"
    assert len(seen) <= 2 * smoke.MAX_ATTEMPTS
    assert all(c["error"] == "unexpected status 500" for c in result.checks)


async def test_connection_errors_do_not_escape():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused for secret-host.internal")

    result, _ = await run(boom)
    assert not result.passed and result.checks[0]["status"] is None
    assert "secret-host" not in str(result.checks[0]["error"])


async def test_response_body_read_is_capped():
    big = b"x" * (smoke.MAX_BODY_BYTES * 3)
    result, _ = await run(lambda r: httpx.Response(200, content=big))
    assert result.checks[0]["bytes"] == smoke.MAX_BODY_BYTES


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://x.test",
        "https://user:pw@preview.example.com",
        "https://",
        "not a url",
    ],
)
async def test_bad_urls_fail_without_a_request(url):
    result, seen = await run(lambda r: httpx.Response(200), url=url)
    assert not result.passed and result.checks == [] and result.error and seen == []


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["healthz"],
        ["//evil.test/x"],
        ["/a b"],
        ["/x\r\nHost: evil"],
        ["/" + "a" * 300],
        ["/ok"] * 11,
        ["/a#frag"],
    ],
)
async def test_bad_paths_are_rejected(paths):
    result, seen = await run(lambda r: httpx.Response(200), paths=paths)
    assert not result.passed and result.checks == [] and seen == []


async def test_base_path_and_port_are_kept():
    result, seen = await run(
        lambda r: httpx.Response(200),
        url="http://preview.example.com:8080/app/",
        paths=["/healthz?x=1"],
    )
    assert result.passed
    assert seen[0].url.path == "/app/healthz" and seen[0].url.query == b"x=1"
    assert seen[0].url.port == 8080 and seen[0].headers["host"] == "preview.example.com:8080"


async def test_timeout_is_clamped():
    # A huge request must not extend the budget past MAX_TIMEOUT; zero still works.
    result, _ = await run(lambda r: httpx.Response(200), timeout_seconds=0)
    assert result.passed
    result, _ = await run(lambda r: httpx.Response(200), timeout_seconds=10_000)
    assert result.passed


async def test_public_wrapper_uses_default_paths_and_simulation_sends_nothing(monkeypatch):
    called = []

    async def fake_run_smoke(url, paths, timeout, **kw):
        called.append((url, paths, timeout, kw))
        return smoke.SmokeResult(passed=True)

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)
    monkeypatch.setattr(preview, "is_simulated", lambda: False)
    result = await preview.run_cloud_smoke_tests("https://preview.example.com")
    assert result.passed and called[0][1] == PreviewOptions().smoke_paths
    assert called[0][3] == {"allow_private": False, "allow_local": False}

    called.clear()
    monkeypatch.setattr(preview, "is_simulated", lambda: True)
    simulated = await preview.run_cloud_smoke_tests("https://preview.example.com", paths=["/a"])
    assert called == []  # no network path was even entered
    assert not simulated.passed and "simulated" in (simulated.error or "")
    assert simulated.checks == [{"path": "/a", "simulated": True, "ok": None, "status": None}]
