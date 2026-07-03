# ADR-0010: Observability — structlog + OpenTelemetry hooks + self-hosted Langfuse

**Status:** Accepted · **Date:** 2026-07-02

## Context

Agent systems fail in ways ordinary request logging can't explain: multi-step runs,
model/tool decisions, token spend. Debuggability from day 1 is a stated engineering
standard; production telemetry (metrics, dashboards, alerting) is Phase 7 scope.

## Decision

- **Structured logs now:** engine logs via **structlog** (JSON to stdout, request ids,
  run ids); web relies on Next.js/Vercel-style structured console logging. Log fields
  are contracts: `run_id`, `conversation_id`, `user_id`, `tier`, `model`.
- **LLM tracing:** every ModelRouter call records model, latency, token usage, and cost.
  **Langfuse (self-hosted)** becomes the trace sink when agent runs land (Phase 1) — spans
  per run → step → model call.
- **OpenTelemetry-shaped from the start:** ids and span-like structure now; the actual
  OTel SDK/collector + Prometheus/Grafana stack arrives in Phase 7 rather than carrying that
  infra while there are no operators.

## Alternatives considered

- **LangSmith** — best LangGraph integration, but SaaS-only ingestion conflicts with
  self-host positioning and adds per-seat cost.
- **Full OTel + Prometheus + Grafana now** — the "proper" stack, but three services and
  dashboard upkeep before there's traffic to observe; deferred, not rejected.
- **Plain print/uvicorn logs** — free, and worthless the first time a 40-step agent run
  needs a post-mortem.

## Consequences

- Log schema discipline starts immediately (reviewed in PRs like API contracts).
- Langfuse joins compose in Phase 1; its absence must never break the engine (fire-and-forget
  exporter).
- Phase 7 revisits this ADR to wire the OTel SDK and metrics/alerting.
