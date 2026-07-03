# ADR-0004: Redis + arq for background jobs; SSE for client streaming

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agent runs (Phase 1) and repo indexing (Phase 2) are long-running jobs that outlive HTTP requests
and must stream progress to the UI. The engine is asyncio end-to-end.

## Decision

- **Redis 7** for queues, pub/sub, and ephemeral state.
- **arq** as the worker framework — asyncio-native, Redis-backed, tiny API; workers run
  the same engine codebase (`arq engine.worker.WorkerSettings`).
- **Server-Sent Events (SSE)** for all server→client streaming (chat tokens, run
  events), proxied through the BFF. Workers publish run events to Redis pub/sub; an
  engine SSE endpoint fans them out.

## Alternatives considered

- **Celery** — battle-tested, but sync-first worker model and heavier config; poor fit
  for an asyncio codebase making streaming LLM calls.
- **Temporal** — excellent durability semantics for multi-step workflows, but a large
  operational dependency; LangGraph checkpointing already gives resumability at the
  graph layer. Revisit if cross-service orchestration outgrows LangGraph.
- **WebSockets** — bidirectional, but our flows are server→client only; SSE is plain
  HTTP (works through the BFF proxy trivially) with built-in reconnect semantics.
- **Postgres LISTEN/NOTIFY as the bus** — fewer moving parts but 8KB payload limits and
  connection-scaling issues; Redis is already present for queues.

## Consequences

- One additional service (Redis) in every environment; acceptable and standard.
- At-least-once job semantics: job handlers must be idempotent (keyed by run/step ids).
- If we later need durable event replay (mission-control history), events also persist
  to `agent_events` in Postgres; Redis remains fire-and-forget transport.
