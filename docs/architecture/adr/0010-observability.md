# ADR-0010: Observability — structlog + OpenTelemetry hooks + self-hosted Langfuse

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agent systems fail in ways ordinary request logging can't explain: multi-step
runs, decisions about which model or tool to use, token spend. Being able to debug
from day one is a stated engineering standard. The heavier production telemetry —
metrics, dashboards, alerting — is Phase 7 scope.

## Decision

- **Structured logs from the start.** The engine logs through structlog (JSON to
  stdout, with request ids and run ids), and the web app relies on Next.js-style
  structured console logging. The log fields are treated as contracts: `run_id`,
  `conversation_id`, `user_id`, `tier`, `model`.
- **LLM tracing.** Every `ModelRouter` call records the model, latency, token
  usage, and cost. Self-hosted Langfuse becomes the trace sink once agent runs
  land in Phase 1, with spans nested per run, then step, then model call.
- **OpenTelemetry-shaped from the beginning.** We carry the ids and a span-like
  structure now, and bring in the actual OTel SDK and collector — along with the
  Prometheus and Grafana stack — in Phase 7, rather than running that
  infrastructure while there is no one to operate it.

## Alternatives considered

- **LangSmith** has the best LangGraph integration, but its SaaS-only ingestion
  conflicts with our self-host positioning and adds a per-seat cost.
- **The full OTel + Prometheus + Grafana stack now** is the "proper" answer, but
  it is three services and ongoing dashboard upkeep before there is any traffic to
  observe. Deferred, not rejected.
- **Plain print or uvicorn logs** are free, and worthless the first time a
  forty-step agent run needs a post-mortem.

## Consequences

- Log-schema discipline starts immediately, reviewed in pull requests the same way
  API contracts are.
- Langfuse joins compose in Phase 1, and its absence must never break the engine —
  the exporter is fire-and-forget.
- Phase 7 comes back to this ADR to wire up the OTel SDK and metrics and alerting.

## Update — 2026-07-13 (Phase 7)

The OTel SDK is wired as planned: instrumentation goes through the OTel API
unconditionally (a no-op unless `OTEL_ENABLED=1` configures the SDK), spans cover
requests, `ModelRouter` calls, and run phases, and OTLP is the export path.
Design note: [PRODUCTION_HARDENING.md](../operations/PRODUCTION_HARDENING.md).
Langfuse remains deferred; an exporter can ride the OTLP path later.
