# ADR-0006: LiteLLM multi-provider gateway, model tiers, and cost controls

**Status:** Accepted · **Date:** 2026-07-02

## Context

Multi-provider LLM support with bring-your-own keys is a product requirement from
day one. On top of that, different workloads deserve different points on the
price-versus-quality curve, and agent runs can burn money without bound if nothing
holds them back.

## Decision

- Every completion and embedding goes through LiteLLM — the in-process SDK, not
  the proxy server — wrapped by our own `ModelRouter` in `engine/llm/router.py`.
  Nothing else in the codebase imports litellm directly.
- **Callers ask for tiers, not models.** They request `planner`, `coder`, or
  `cheap`, and the environment maps those tiers to concrete models
  (`MODEL_PLANNER`, `MODEL_CODER`, `MODEL_CHEAP`), defaulting to Anthropic models
  named with provider prefixes such as `anthropic/claude-sonnet-4-6`.
- **Keys** come from the environment in development; per-user encrypted
  bring-your-own keys (AES-GCM) arrive with the Phase 1 schema.
- **Cost is tracked per call.** The `ModelRouter` records tokens and cost from
  litellm's usage data, and per-run budget caps abort a run that spends past its
  allowance.
- **`LLM_FAKE=1`** returns deterministic canned streams, so tests, CI, and offline
  development never need a real key.

## Alternatives considered

- **Direct provider SDKs behind our own interface** would mean fewer dependencies
  and the tightest possible control, but we would be hand-writing every provider
  times every concern — streaming, tools, usage accounting.
- **The LiteLLM proxy server** (as a separate service) centralizes keys and limits
  across many callers, but we only have one caller. The in-process SDK is simpler
  today, and the proxy stays available as a drop-in upgrade later.
- **OpenRouter** gives instant multi-provider access through a single API, but it
  adds a paid middleman and works against our self-host, bring-your-own-keys
  positioning.

## Consequences

- LiteLLM normalizes the differences between providers (tool-calling formats,
  reasoning parameters), though edge cases will still leak through and land in the
  `ModelRouter` to absorb.
- LiteLLM moves fast as a dependency, so we pin it and upgrade deliberately.
- Because tiers are indirection over concrete models, evaluations have to run
  against a specific model configuration, not just against a tier.
