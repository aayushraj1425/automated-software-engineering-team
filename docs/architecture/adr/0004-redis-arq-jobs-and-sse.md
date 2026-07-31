# ADR-0004: Redis + arq for background jobs; SSE for client streaming

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agent runs and repository indexing are long-running jobs. They outlive a single
HTTP request, and they need to stream their progress back to the UI as they go.
The engine is asyncio from top to bottom, so whatever we pick should feel native
there.

## Decision

- **Redis 7** handles queues, pub/sub, and ephemeral state.
- **arq** is the worker framework. It is asyncio-native, Redis-backed, and has a
  small API, and its workers run the same engine codebase
  (`arq engine.worker.WorkerSettings`).
- **Server-Sent Events** carry all server-to-client streaming — chat tokens and
  run events alike — proxied through the BFF. Workers publish run events to Redis
  pub/sub, and an engine SSE endpoint fans them out to connected clients.

## Alternatives considered

- **Celery** is battle-tested, but its worker model is sync-first and its
  configuration is heavier. That is a poor fit for an asyncio codebase that spends
  its time making streaming LLM calls.
- **Temporal** has excellent durability semantics for multi-step workflows, but it
  is a large operational dependency, and LangGraph's checkpointing already gives
  us resumability at the graph layer. Worth revisiting if cross-service
  orchestration ever outgrows LangGraph.
- **WebSockets** are bidirectional, but our streams only ever flow from server to
  client. SSE is plain HTTP — so it passes through the BFF proxy without fuss —
  and it comes with reconnection semantics built in.
- **Postgres LISTEN/NOTIFY as the bus** would mean fewer moving parts, but its
  8 KB payload limit and connection-scaling behavior get in the way, and Redis is
  already here for the queues.

## Consequences

- Every environment runs one more service, Redis, which is standard and
  acceptable.
- Jobs have at-least-once semantics, so handlers must be idempotent (keyed by run
  and step ids).
- When we need durable event replay for mission-control history, the events are
  already persisted to `agent_events` in Postgres; Redis stays a fire-and-forget
  transport.
