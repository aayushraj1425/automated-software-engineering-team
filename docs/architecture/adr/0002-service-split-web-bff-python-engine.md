# ADR-0002: Two services — Next.js web/BFF + Python AI engine

**Status:** Accepted · **Date:** 2026-07-02

## Context

We need two things that pull in opposite directions: a polished product UI with
authentication, and an AI runtime built on the strongest agent ecosystem
available. That ecosystem — LangGraph, LiteLLM, tree-sitter bindings, the broader
ML tooling — is Python-first, while the UI ecosystem is TypeScript-first. Rather
than compromise on either, we let each live in the language that suits it.

## Decision

Two applications:

- **apps/web (Next.js 15)** is the UI and also a backend-for-frontend. It owns
  browser sessions through better-auth, signs a short-lived HS256 service JWT
  (`ENGINE_SERVICE_SECRET`, `sub` = user id, roughly 60-second expiry), and
  proxies REST and SSE calls to the engine. The engine is never exposed to
  browsers.
- **apps/engine (FastAPI, Python 3.12)** does all the AI work: model routing,
  agent graphs, repository operations, and background workers. It also owns the
  domain schema through Alembic.

## Alternatives considered

- **A Node-only stack** (Next.js plus a Node agent runtime) keeps everything in
  one language, but the Python agent and parsing ecosystem is materially
  stronger. We would end up reimplementing the maturity of LangGraph and
  tree-sitter ourselves.
- **A separate API gateway service** (NestJS or Fastify sitting between web and
  engine) would be clean, but it is a third deployable with no responsibility the
  BFF cannot already cover. We can add it later, when non-browser clients such as
  a CLI or IDE plugin need a public API.
- **A Python-only stack** (FastAPI with Jinja or HTMX) is a poor fit for a rich
  workspace UI.

## Consequences

- The contract boundary is explicit: the engine's OpenAPI spec generates the
  TypeScript types in `packages/shared`.
- The service JWT carries user identity to the engine without duplicating auth
  logic on both sides.
- There are two runtimes to operate, which we accept — both are containerized the
  same way in production.
- The day a public API or CLI arrives is the day it makes sense to promote the
  engine behind a real gateway.
