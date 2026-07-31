# ADR-0001: Monorepo with pnpm workspaces + Turborepo

**Status:** Accepted · **Date:** 2026-07-02

## Context

The platform is made of several parts that move together: a TypeScript web app, a
Python AI engine, the shared API types between them, the infrastructure
definitions, and a fair amount of documentation. In practice they change as a
unit — a single change to the API contract usually touches the web app, the
engine, and the shared types in the same pull request. The team is small, so we
want as little coordination overhead as possible. One more constraint shapes the
choice: the repository lives in a OneDrive-synced folder on Windows, and OneDrive
handles symlinks and junctions poorly.

## Decision

Keep everything in one repository, managed with pnpm workspaces and Turborepo as
the task runner. The Python app takes part as a workspace package whose npm
scripts delegate to `uv run …`, so a command like `turbo run lint` or
`turbo run test` fans out across both the JavaScript and Python sides at once.
pnpm is pinned to `node-linker=hoisted` in `.npmrc` so that `node_modules` holds
real files rather than junctions, which keeps OneDrive's sync happy.

## Alternatives considered

- **Nx** offers richer graph features and code generators, but it asks for more
  configuration and more buy-in to its conventions than a small team needs right
  now.
- **A polyrepo** (separate web, engine, and infra repositories) would draw
  cleaner ownership lines, but then every cross-cutting change — an API contract,
  for one — would need coordinated pull requests across repositories. That's a
  cost we don't need to pay yet.
- **Bazel or Pants** would give us hermetic, highly scalable builds, but the
  toolchain cost is far more than this project can justify today.

## Consequences

- A single `pnpm install` plus `uv sync` bootstraps the whole thing, and there is
  one CI pipeline to maintain.
- Turborepo's caching keeps lint and test runs fast as the repository grows.
- The hoisted linker gives up pnpm's strict dependency isolation, which means
  phantom dependencies become possible. We accept that trade for OneDrive safety,
  and it is worth revisiting if the checkout ever moves off OneDrive.
- Python tooling stays uv-native; Turborepo only orchestrates it.
