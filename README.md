# ASEP — AI Software Engineering Platform

An AI-native software engineering platform that assists across the whole software
development lifecycle: a multi-agent engineering team (PM, Backend, Frontend, DevOps,
Reviewer), repository intelligence, planning, implementation, code review, testing,
documentation, and deployment.

> Working codename: **asep**. Status: **Milestone 0 — Foundation** (walking skeleton).

## Architecture at a glance

```
Browser ──► apps/web   Next.js 15 (UI + BFF: better-auth sessions, SSE proxy)
                │  REST + SSE (signed service JWT)
                ▼
            apps/engine FastAPI (Python 3.12)
              ├─ ModelRouter over LiteLLM (multi-provider, tiering, BYO keys)
              ├─ LangGraph runtime (agents, Postgres checkpoints)
              └─ arq workers (Redis) — agent runs (M1+)
        Postgres 16 + pgvector ─── Redis 7 ─── MinIO (S3-compatible)
```

Full design docs live in [`docs/`](docs/): [PRD](docs/prd/PRD.md) ·
[Architecture](docs/architecture/OVERVIEW.md) · [ADRs](docs/architecture/adr/) ·
[Roadmap](docs/ROADMAP.md) · [Backlog](docs/BACKLOG.md) · [Security](docs/SECURITY.md)

## Repo layout

| Path | What it is |
|---|---|
| `apps/web` | Next.js 15 + TypeScript + Tailwind — product UI and auth BFF |
| `apps/engine` | FastAPI + LangGraph + LiteLLM — the AI engine (uv-managed) |
| `packages/shared` | OpenAPI-generated TypeScript client types for the engine API |
| `infra/docker` | Local dev services (Postgres + pgvector, Redis, MinIO) |
| `docs/` | PRD, architecture, ADRs, roadmap, living backlog |

## Quickstart (local dev)

Prerequisites: Node 22+, pnpm 9+, Python 3.12+, [uv](https://docs.astral.sh/uv/),
Docker Desktop (WSL2 on Windows).

```sh
# 1. Environment — one .env at the repo root drives everything
cp .env.example .env          # then add at least one LLM provider key
                              # (or set LLM_FAKE=1 to run without any key)

# 2. Start dev services (Postgres, Redis, MinIO)
pnpm db:up

# 3. Install dependencies
pnpm install
cd apps/engine && uv sync && cd ../..

# 4. Apply database migrations (engine schema + auth schema)
pnpm db:migrate

# 5. Run everything (web on :3000, engine on :8000)
pnpm dev
```

Sign up at http://localhost:3000/sign-up (dev credentials login), then chat at
http://localhost:3000/chat.

## Common commands

```sh
pnpm dev            # run web + engine dev servers via turbo
pnpm lint           # eslint + ruff across the workspace
pnpm typecheck      # tsc + pyright
pnpm test           # vitest + pytest
pnpm e2e            # Playwright smoke (needs db up; uses LLM_FAKE)
pnpm db:up          # start dev services
pnpm db:migrate     # alembic upgrade head + better-auth migrate
```

## Contributing

Every feature ships the full loop: architecture note → API spec → schema migration →
UI/UX → implementation → tests → docs → performance/security pass. The PR template
enforces this Definition of Done. See [docs/BACKLOG.md](docs/BACKLOG.md) for what's next.
