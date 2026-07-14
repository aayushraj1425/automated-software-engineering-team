"""Per-caller rate limiting: a token bucket in front of the API (Phase 7).

Each caller gets RATE_LIMIT_BURST tokens refilling at RATE_LIMIT_PER_MINUTE/60
per second — bursts pass, sustained floods get a 429 with Retry-After. Callers
are keyed by the verified JWT subject (one user cannot starve another); a
missing or invalid token falls back to the client IP, so an unauthenticated
flood is contained without letting fabricated subjects mint fresh buckets.
RATE_LIMIT_PER_MINUTE=0 (the default) disables everything. Per replica by
design — see docs/architecture/RATE_LIMITING.md.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

import jwt

from engine.config import get_settings

# Prune idle buckets so the table cannot grow without bound.
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
        self.buckets: dict[str, TokenBucket] = {}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        settings = get_settings()
        per_minute = settings.rate_limit_per_minute
        if scope["type"] != "http" or scope["path"] == "/healthz" or per_minute <= 0:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        self._prune(now)
        key = _caller_key(scope)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = TokenBucket(
                tokens=float(settings.rate_limit_burst), last_refill=now
            )
        retry_after = bucket.take(float(settings.rate_limit_burst), per_minute / 60.0, now)
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

    def _prune(self, now: float) -> None:
        if len(self.buckets) <= _PRUNE_ABOVE:
            return
        stale = [k for k, b in self.buckets.items() if now - b.last_refill > _IDLE_SECONDS]
        for key in stale:
            del self.buckets[key]
