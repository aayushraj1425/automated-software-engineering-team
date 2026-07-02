# ADR-0006: LiteLLM multi-provider gateway, model tiers, and cost controls

**Status:** Accepted · **Date:** 2026-07-02

## Context

Product decision (user): multi-provider LLM support with bring-your-own keys from day 1.
Different workloads deserve different price/quality points; agent runs can burn money
unboundedly if uncontrolled.

## Decision

- All completions/embeddings go through **LiteLLM** (SDK, in-process — not the proxy
  server) wrapped by our **`ModelRouter`** (`engine/llm/router.py`). Nothing else in the
  codebase imports litellm.
- **Tiers, not models, in code:** callers ask for `planner` / `coder` / `cheap`;
  env maps tiers to concrete models (`MODEL_PLANNER`, `MODEL_CODER`, `MODEL_CHEAP`),
  defaulting to Anthropic models with provider prefixes (e.g. `anthropic/claude-sonnet-4-6`).
- **Keys:** provider API keys via env in dev; per-user encrypted BYO keys (AES-GCM)
  arrive with M1's schema.
- **Cost controls:** ModelRouter records tokens/cost per call (litellm usage data);
  M1 adds per-run budget caps that abort runs exceeding their allowance.
- **`LLM_FAKE=1`** returns deterministic canned streams — tests, CI, and offline dev
  never need real keys.

## Alternatives considered

- **Direct provider SDKs behind our own interface** — fewer dependencies and tightest
  control, but we'd hand-write N providers × (streaming, tools, usage accounting).
- **LiteLLM proxy server** (separate service) — centralizes keys/limits across many
  services, but we have one caller; in-process SDK is simpler now and the proxy remains
  a drop-in upgrade.
- **OpenRouter** — instant multi-provider via one API, but adds a paid middleman and
  conflicts with self-host/BYO-keys positioning.

## Consequences

- Provider capability differences (tool-calling formats, reasoning params) get
  normalized by LiteLLM; edge cases will still leak and land in ModelRouter to absorb.
- LiteLLM is a fast-moving dependency: pin and upgrade deliberately.
- Tier indirection means evals must run per concrete model config, not just per tier.
