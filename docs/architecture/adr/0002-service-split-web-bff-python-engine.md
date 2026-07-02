# ADR-0002: Two services — Next.js web/BFF + Python AI engine

**Status:** Accepted · **Date:** 2026-07-02

## Context

We need a product UI with authentication *and* an AI runtime with the strongest agent
ecosystem. The AI ecosystem (LangGraph, LiteLLM, tree-sitter bindings, ML tooling) is
Python-first; the UI ecosystem is TypeScript-first.

## Decision

Two applications:

- **apps/web (Next.js 15)** — UI plus a *backend-for-frontend*: owns browser sessions
  (better-auth), signs a short-lived HS256 **service JWT** (`ENGINE_SERVICE_SECRET`,
  `sub`=user id, ~60s expiry) and proxies REST/SSE to the engine. The engine is never
  exposed to browsers.
- **apps/engine (FastAPI, Python 3.12)** — all AI work: model routing, agent graphs,
  repo operations, background workers; owns the domain schema via Alembic.

## Alternatives considered

- **Node-only stack** (Next.js + Node agent runtime) — one language, but the Python
  agent/parsing ecosystem is materially stronger; we'd reimplement LangGraph/tree-sitter
  maturity.
- **Separate API gateway service** (NestJS/Fastify between web and engine) — clean, but
  a third deployable with no current responsibilities the BFF can't cover. Add later if
  non-browser clients (CLI, IDE plugins) need a public API.
- **Python-only** (FastAPI + Jinja/HTMX) — weak fit for a rich workspace UI.

## Consequences

- Clear contract boundary: engine OpenAPI spec → generated TS types (packages/shared).
- Service JWT keeps user identity flowing to the engine without duplicating auth.
- Two runtimes to operate; acceptable, both are containerized identically in prod.
- A future public API/CLI will motivate promoting the engine behind a real gateway.
