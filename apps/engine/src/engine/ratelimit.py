"""Per-caller rate limiting: a token bucket in front of the API (Phase 7).

Each caller gets RATE_LIMIT_BURST tokens refilling at RATE_LIMIT_PER_MINUTE/60
per second — bursts pass, sustained floods get a 429 with Retry-After. Callers
are keyed by the verified JWT subject (one user cannot starve another); a
missing or invalid token falls back to the client IP, so an unauthenticated
flood is contained without letting fabricated subjects mint fresh buckets.
RATE_LIMIT_PER_MINUTE=0 (the default) disables everything.

The bucket lives in-process per replica by default; RATE_LIMIT_SHARED=1 moves
it into Redis so every replica draws from one window, degrading back to the
in-process bucket if Redis is unreachable — see docs/architecture/RATE_LIMITING.md.
"""

import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import jwt
from redis import asyncio as aioredis

from engine.config import get_settings

logger = logging.getLogger(__name__)

# Prune idle buckets so the in-process table cannot grow without bound.
_PRUNE_ABOVE = 5000
_IDLE_SECONDS = 600.0


@dataclass
class TokenBucket:
    tokens: float
    last_refill: float

    def take(self, capacity: float, per_second: float, now: float) -> float:
        """Take one token; 0.0 when allowed, else seconds until the next token."""
        self.tokens = min(capacity, self.tokens + (now - self.last_refill) * per_second)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / per_second


class LocalLimiter:
    """The in-process bucket table — one replica's own ceiling. Uses a
    monotonic clock, so a wall-clock jump never hands out free tokens."""

    def __init__(self) -> None:
        self.buckets: dict[str, TokenBucket] = {}

    async def take(self, key: str, capacity: float, per_second: float) -> float:
        now = time.monotonic()
        self._prune(now)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = TokenBucket(tokens=capacity, last_refill=now)
        return bucket.take(capacity, per_second, now)

    def _prune(self, now: float) -> None:
        if len(self.buckets) <= _PRUNE_ABOVE:
            return
        stale = [k for k, b in self.buckets.items() if now - b.last_refill > _IDLE_SECONDS]
        for key in stale:
            del self.buckets[key]


# The same refill-then-take arithmetic as TokenBucket, run atomically inside
# Redis so two replicas cannot both win the last token. The wall clock is
# passed in (ARGV[3]) rather than read from Redis, and the key is given a TTL a
# little past a full refill so idle callers expire on their own — the shared
# path needs no pruning sweep. Returns the retry-after seconds (0 = allowed).
_TAKE_SCRIPT = """
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local ts = tonumber(redis.call('HGET', KEYS[1], 'ts'))
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
if tokens == nil then
  tokens = capacity
  ts = now
end
tokens = math.min(capacity, tokens + (now - ts) * rate)
local retry = 0.0
if tokens >= 1.0 then
  tokens = tokens - 1.0
else
  retry = (1.0 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)
return tostring(retry)
"""


class SharedLimiter:
    """One bucket across every replica, kept in Redis. On any Redis error it
    delegates to the in-process fallback and warns once, so a Redis outage
    drops the ceiling to per-replica — never a hard dependency or a 429 storm."""

    def __init__(self, client: aioredis.Redis, fallback: LocalLimiter) -> None:
        self._script = client.register_script(_TAKE_SCRIPT)
        self._fallback = fallback
        self._warned = False

    async def take(self, key: str, capacity: float, per_second: float) -> float:
        ttl = int(capacity / per_second) + 60 if per_second > 0 else 60
        try:
            retry = await self._script(
                keys=[f"ratelimit:{key}"],
                args=[capacity, per_second, time.time(), ttl],
            )
            return float(retry)
        except Exception:  # Redis unreachable, script error — degrade, do not fail the request
            if not self._warned:
                logger.warning("rate limiter: Redis unavailable, degrading to per-replica buckets")
                self._warned = True
            return await self._fallback.take(key, capacity, per_second)


_client: aioredis.Redis | None = None


def _get_client() -> aioredis.Redis:
    """The shared rate-limit Redis connection, with tight timeouts so a dead
    Redis surfaces as an error the limiter can degrade on, not a stall."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
    return _client


async def dispose_ratelimit() -> None:
    """Close the shared Redis connection (engine shutdown). Never raises —
    a connection bound to an already-closed event loop just gets dropped."""
    global _client
    if _client is not None:
        client, _client = _client, None
        with suppress(Exception):
            await client.aclose()


def _caller_key(scope: dict) -> str:
    """user:<sub> for a verifiable bearer token, else ip:<client>."""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            token = value.decode("latin-1").removeprefix("Bearer ")
            try:
                payload = jwt.decode(
                    token,
                    get_settings().engine_service_secret,
                    algorithms=["HS256"],
                    options={"require": ["exp", "sub"]},
                )
                return f"user:{payload['sub']}"
            except jwt.PyJWTError:
                break  # unverifiable tokens are anonymous traffic
    client = scope.get("client")
    return f"ip:{client[0] if client else 'unknown'}"


class RateLimitMiddleware:
    """Pure ASGI so SSE streams pass through; sits inside the tracing
    middleware, so 429s land in the request metrics like any response."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.local = LocalLimiter()
        self.shared: SharedLimiter | None = None

    def _limiter(self, settings: Any) -> LocalLimiter | SharedLimiter:
        if not settings.rate_limit_shared:
            return self.local
        if self.shared is None:
            self.shared = SharedLimiter(_get_client(), fallback=self.local)
        return self.shared

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        settings = get_settings()
        per_minute = settings.rate_limit_per_minute
        if scope["type"] != "http" or scope["path"] == "/healthz" or per_minute <= 0:
            await self.app(scope, receive, send)
            return

        key = _caller_key(scope)
        retry_after = await self._limiter(settings).take(
            key, float(settings.rate_limit_burst), per_minute / 60.0
        )
        if retry_after > 0.0:
            body = json.dumps({"detail": "Too many requests — slow down"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(max(1, round(retry_after))).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
