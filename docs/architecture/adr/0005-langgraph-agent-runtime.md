# ADR-0005: LangGraph as the agent runtime

**Status:** Accepted · **Date:** 2026-07-02

## Context

The core of the product is a team of specialist agents — Product Manager,
Backend, Frontend, DevOps, Reviewer, and others — collaborating through
structured task planning. That collaboration needs human approval gates, live
streaming of progress, the ability to resume after a crash or restart, and a full
audit trail of what happened.

## Decision

Build the agent runtime on LangGraph:

- Agent teams are modeled as StateGraphs, where a Supervisor node routes work to
  the specialist nodes.
- A Postgres checkpointer (`langgraph-checkpoint-postgres`) persists every step,
  so runs survive restarts and can be replayed or audited afterward.
- Interrupts implement the human gates — plan approval, and confirmation before a
  destructive action.
- Custom stream writers (`stream_mode="custom"`) emit the token and step events
  that map onto our SSE channel.
- LLM calls inside nodes go through our own `ModelRouter` (ADR-0006) rather than
  LangChain's model wrappers, which keeps all provider handling in one place.

## Alternatives considered

- **A custom runtime** (asyncio plus our own state machine) would give us total
  control and no framework drift, but we would have to reimplement checkpointing,
  interrupts, replay, and streaming — a poor use of a small team's time. The
  `ModelRouter` boundary keeps this escape hatch open if we ever change our mind.
- **CrewAI or AutoGen** are quick ways to demo role-playing teams, but they have
  weaker durability semantics and give us less control over exact state
  transitions than a graph we define ourselves.
- **The Claude Agent SDK** has an excellent single-agent loop, but it would couple
  the runtime to one provider, and staying multi-provider is a deliberate product
  requirement.

## Consequences

- LangGraph version drift is a genuine maintenance cost, so we pin minor versions
  and wrap its API inside `engine/agents/` to keep upgrades localized.
- Graph state has to stay JSON-serializable for checkpointing to work.
- The checkpointer manages its own tables (created through `setup()`), which we
  document as a third schema owner alongside Alembic and better-auth.
