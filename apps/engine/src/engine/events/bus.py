"""The run event bus: Redis wakes the stream, Postgres holds the events.

Redis carries no payloads — a ping on the run's channel just means "new rows
in agent_events, go read them". So a lost ping (or Redis being down entirely)
costs at most one heartbeat of latency, never an event, and there is nothing
to replay when Redis restarts. Design note:
docs/architecture/RUN_EVENT_STREAMING.md (ADR-0004 chose Redis for this).
"""

import asyncio
import uuid
from contextlib import suppress

import structlog
from redis import asyncio as aioredis
from redis.asyncio.client import PubSub

from engine.config import get_settings

log = structlog.get_logger()

# How long a stream sleeps between Postgres checks when no ping arrives.
# This heartbeat is the whole fallback story: without Redis the stream still
# works, just up to this much later.
HEARTBEAT_SECONDS = 2.0

_client: aioredis.Redis | None = None
_warned_unavailable = False


def _channel(run_id: uuid.UUID) -> str:
    return f"run-events:{run_id}"


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        # Tight socket timeouts: a dead Redis must degrade the bus to
        # heartbeat pacing, never stall a run between commits.
        _client = aioredis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=5,
        )
    return _client


async def dispose_bus() -> None:
    """Close the shared Redis connection (engine shutdown). Never raises —
    a connection bound to an already-closed event loop just gets dropped."""
    global _client
    if _client is not None:
        client, _client = _client, None
        with suppress(Exception):  # a dead-loop connection just gets dropped
            await client.aclose()


async def publish_run_ping(run_id: uuid.UUID) -> None:
    """Wake anyone streaming this run's timeline. Never raises — with Redis
    down the ping is dropped (logged once) and the heartbeat covers it."""
    global _client, _warned_unavailable
    try:
        await _get_client().publish(_channel(run_id), "1")
        _warned_unavailable = False
    except Exception as exc:
        # Drop the client so the next use rebuilds it — the failure may be a
        # connection bound to a dead event loop, not a dead Redis.
        _client = None
        if not _warned_unavailable:
            _warned_unavailable = True
            log.warning("event_bus.unavailable", error=str(exc)[:200])


class RunEventSubscription:
    """One stream's wake-up signal: waits for a Redis ping, or a heartbeat.

    Use as an async context manager. `wait()` returns after a ping or after
    HEARTBEAT_SECONDS, whichever comes first — the caller re-reads Postgres
    either way, so the distinction never matters for correctness.
    """

    def __init__(self, run_id: uuid.UUID):
        self._run_id = run_id
        self._pubsub: PubSub | None = None

    async def __aenter__(self) -> "RunEventSubscription":
        global _client
        try:
            pubsub = _get_client().pubsub()
            await pubsub.subscribe(_channel(self._run_id))
            self._pubsub = pubsub
        except Exception:
            _client = None  # rebuild on next use (see publish_run_ping)
            self._pubsub = None  # heartbeat-only mode
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._pubsub is not None:
            with suppress(Exception):  # already tearing down
                await self._pubsub.unsubscribe()
                await self._pubsub.aclose()

    async def wait(self) -> None:
        if self._pubsub is None:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            return
        try:
            await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
            )
        except Exception:
            # Redis dropped mid-stream: fall back to heartbeat-only pacing.
            self._pubsub = None
            await asyncio.sleep(HEARTBEAT_SECONDS)
