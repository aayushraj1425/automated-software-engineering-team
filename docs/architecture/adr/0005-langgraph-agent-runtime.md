# ADR-0005: LangGraph as the agent runtime

**Status:** Accepted · **Date:** 2026-07-02

## Context

Goal 3 requires a *team* of specialist agents (PM, Backend, Frontend, DevOps, Reviewer,
…) collaborating through structured task planning with human approval gates, live
streaming, resumability after crashes/restarts, and full auditability.

## Decision

Build the agent runtime on **LangGraph**:

- Agent teams are **StateGraphs** — a Supervisor node routes work to specialist nodes.
- **Postgres checkpointer** (`langgraph-checkpoint-postgres`) persists every step, so
  runs survive restarts and can be replayed/audited.
- **Interrupts** implement human gates (plan approval, destructive-action confirmation).
- `stream_mode="custom"` writers emit token/step events that map onto our SSE channel.
- LLM calls inside nodes go through our `ModelRouter` (ADR-0006), *not* LangChain model
  wrappers, keeping provider handling in one place.

## Alternatives considered

- **Custom runtime** (asyncio + our own state machine) — full control, no framework
  drift, but we would reimplement checkpointing, interrupts, replay, and streaming;
  poor use of a small team. The `ModelRouter` boundary preserves this escape hatch.
- **CrewAI / AutoGen** — fast to demo role-play teams, but weaker durability semantics
  and less control over exact state transitions than a graph we define ourselves.
- **Claude Agent SDK** — excellent single-agent loop, but couples the runtime to one
  provider while the platform is multi-provider by decision (user requirement).

## Consequences

- LangGraph version drift is a real maintenance cost; pin minor versions, wrap its API
  in `engine/agents/` so upgrades localize.
- Graph state must stay JSON-serializable for checkpointing.
- The checkpointer manages its own tables (created via `setup()`), documented as a
  third schema owner alongside Alembic and better-auth.
