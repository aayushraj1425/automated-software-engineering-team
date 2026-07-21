"""Rate limiting: per-caller token bucket in front of the API.

Off by default (RATE_LIMIT_PER_MINUTE=0), so every other test runs unlimited;
these tests opt in by monkeypatching the cached settings object. Design note:
docs/architecture/RATE_LIMITING.md.
"""

import uuid

import pytest
from redis import asyncio as aioredis

from engine.config import get_settings
from engine.ratelimit import LocalLimiter, SharedLimiter, TokenBucket
from tests.conftest import auth_headers


@pytest.fixture
def limited(monkeypatch):
    """Two requests of burst, refilling at one token per second."""
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 60)
    monkeypatch.setattr(get_settings(), "rate_limit_burst", 2)


async def _redis_or_skip() -> aioredis.Redis:
    """A live Redis on the caller's own event loop, or skip. Created inside the
    test (not a fixture) so the connection is bound to the test's loop — the
    default fixture loop scope is the session, which would cross loops. CI's
    engine job runs no Redis, so these tests skip there; locally they run."""
    client = aioredis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=2,
    )
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis is not available")
    return client


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


def test_token_bucket_refills_over_time():
    bucket = TokenBucket(tokens=1.0, last_refill=0.0)
    assert bucket.take(capacity=2.0, per_second=1.0, now=0.0) == 0.0  # the last token
    retry = bucket.take(capacity=2.0, per_second=1.0, now=0.0)
    assert retry == pytest.approx(1.0)  # empty: one second to the next token
    assert bucket.take(capacity=2.0, per_second=1.0, now=5.0) == 0.0  # refilled (and capped)


async def test_burst_passes_then_429_with_retry_after(client, limited):
    headers = _headers()
    for _ in range(2):
        assert (await client.get("/v1/repositories", headers=headers)).status_code == 200

    resp = await client.get("/v1/repositories", headers=headers)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert "slow down" in resp.json()["detail"]


async def test_users_have_independent_buckets(client, limited):
    exhausted = _headers()
    for _ in range(3):
        await client.get("/v1/repositories", headers=exhausted)
    assert (await client.get("/v1/repositories", headers=exhausted)).status_code == 429

    other = _headers()
    assert (await client.get("/v1/repositories", headers=other)).status_code == 200


async def test_healthz_is_never_throttled(client, limited):
    for _ in range(10):
        assert (await client.get("/healthz")).status_code == 200


async def test_unverifiable_tokens_share_the_ip_bucket(client, limited):
    garbage = {"Authorization": "Bearer not-a-real-token"}
    statuses = [
        (await client.get("/v1/repositories", headers=garbage)).status_code for _ in range(3)
    ]
    # 401 (past the limiter, failed auth) twice, then the shared IP bucket is dry.
    assert statuses[:2] == [401, 401]
    assert statuses[2] == 429


async def test_disabled_by_default_means_unlimited(client):
    headers = _headers()
    for _ in range(5):
        assert (await client.get("/v1/repositories", headers=headers)).status_code == 200


# ── The shared window: one bucket across replicas, kept in Redis ────────────


async def test_shared_limiter_enforces_one_window():
    """Burst passes, then the shared Redis bucket is dry — the same arithmetic
    as the in-process bucket, but atomic and shared (RATE_LIMITING.md)."""
    client = await _redis_or_skip()
    try:
        limiter = SharedLimiter(client, fallback=LocalLimiter())
        key = f"test:{uuid.uuid4().hex}"

        assert await limiter.take(key, capacity=2.0, per_second=1.0) == 0.0
        assert await limiter.take(key, capacity=2.0, per_second=1.0) == 0.0
        retry = await limiter.take(key, capacity=2.0, per_second=1.0)
        assert retry == pytest.approx(1.0, abs=0.3)  # empty: ~one second to the next token
    finally:
        await client.aclose()


async def test_shared_limiter_keeps_callers_separate():
    client = await _redis_or_skip()
    try:
        limiter = SharedLimiter(client, fallback=LocalLimiter())
        dry = f"test:{uuid.uuid4().hex}"
        assert await limiter.take(dry, capacity=1.0, per_second=1.0) == 0.0
        assert await limiter.take(dry, capacity=1.0, per_second=1.0) > 0.0  # dry

        fresh = f"test:{uuid.uuid4().hex}"
        assert await limiter.take(fresh, capacity=1.0, per_second=1.0) == 0.0  # its own tokens
    finally:
        await client.aclose()


class _DeadRedis:
    """A Redis whose script call always raises — stands in for an outage
    without needing a real server, so this runs in CI."""

    def register_script(self, script: str):
        async def _raise(*args, **kwargs):
            raise ConnectionError("redis down")

        return _raise


async def test_shared_limiter_degrades_to_local_when_redis_is_down():
    """A Redis outage drops the ceiling to the per-replica bucket — never a
    hard dependency, never a 429 storm."""
    local = LocalLimiter()
    limiter = SharedLimiter(_DeadRedis(), fallback=local)
    key = f"test:{uuid.uuid4().hex}"

    assert await limiter.take(key, capacity=1.0, per_second=1.0) == 0.0  # local allows
    assert await limiter.take(key, capacity=1.0, per_second=1.0) > 0.0  # local now dry
    assert limiter._warned is True  # and it said so, once
