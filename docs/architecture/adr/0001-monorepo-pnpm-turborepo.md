# ADR-0001: Monorepo with pnpm workspaces + Turborepo

**Status:** Accepted · **Date:** 2026-07-02

## Context

The platform spans a TypeScript web app, a Python AI engine, shared API types, infra,
and heavy documentation. They evolve together (API contract changes touch web + engine
+ shared in one PR). The team is small; coordination overhead must stay near zero.
The checkout lives in a OneDrive-synced folder on Windows, which mishandles
symlinks/junctions.

## Decision

One monorepo managed by **pnpm workspaces** with **Turborepo** as the task runner.
The Python app participates as a workspace package whose npm scripts delegate to
`uv run …`, so `turbo run lint/test/dev` fans out across both stacks.
pnpm is pinned to `node-linker=hoisted` (`.npmrc`) so node_modules contains real files,
not junctions, keeping OneDrive sync safe.

## Alternatives considered

- **Nx** — richer graph features and generators, but heavier configuration and more
  framework buy-in than a small team needs now.
- **Polyrepo** (web / engine / infra) — clean ownership boundaries, but cross-cutting
  changes (API contracts) would need coordinated multi-repo PRs; premature.
- **Bazel/Pants** — hermetic and scalable, far too much toolchain cost today.

## Consequences

- Single `pnpm install` + `uv sync` bootstraps everything; one CI pipeline.
- Turbo caching keeps lint/test fast as the repo grows.
- Hoisted linker forfeits pnpm's strict isolation (phantom dependencies possible);
  acceptable trade for OneDrive safety — revisit if the checkout moves off OneDrive.
- Python tooling stays uv-native; turbo only orchestrates.
