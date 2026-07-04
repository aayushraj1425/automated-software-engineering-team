# CLAUDE.md

ASEP — AI Software Engineering Platform. pnpm + Turborepo monorepo: Next.js web app,
FastAPI AI engine, shared OpenAPI types. Program plan and phase status live in
`docs/ROADMAP.md`; the living backlog is `docs/BACKLOG.md`. Decisions are recorded as
ADRs in `docs/architecture/adr/` — read the relevant ADR before changing architecture.
Naming convention: descriptive names only — never shorthand codes. Phases are
"Phase 1 — Multi-Agent Engineering Team" (not "M1"); backlog work is referenced by
workstream and item name, e.g. "Agent Runtime — Postgres checkpointing per run"
(not "Task 1.1.4" or "M1-E1-T4"). The user considers coded identifiers unprofessional.

## Commands

```sh
pnpm dev / lint / typecheck / test      # turbo fans out to all workspaces
pnpm db:up                              # docker compose dev services
pnpm db:migrate                         # alembic + better-auth migrations
pnpm e2e                                # Playwright smoke (db must be up)
```

Engine-only (run inside `apps/engine`): `uv sync`, `uv run pytest`,
`uv run ruff check .`, `uv run ruff format --check .` (CI enforces formatting —
run before every push), `uv run pyright`, `uv run alembic upgrade head`.

## Layout

- `apps/web` — Next.js 15 App Router, TS strict, Tailwind v4. better-auth handles
  identity (its tables are created by `pnpm --filter web auth:migrate`, NOT alembic).
  BFF routes under `src/app/api/` sign a service JWT and proxy to the engine.
- `apps/engine` — Python 3.12, FastAPI, SQLAlchemy 2 async (psycopg3), Alembic,
  LangGraph, LiteLLM. Source in `src/engine/`, tests in `tests/`.
- `packages/shared` — generated engine API types; regenerate with `pnpm generate`.
- `infra/docker/docker-compose.dev.yml` — Postgres 16 + pgvector, Redis 7, MinIO.

## Conventions

- One `.env` at the repo root feeds compose, the engine (pydantic-settings), and the
  web app (loaded in `next.config.ts`). Never commit `.env`; update `.env.example`.
- LLM calls go through `engine/llm/router.py` (`ModelRouter`) — never call litellm
  directly elsewhere. Tiers: planner / coder / cheap, set via `MODEL_*` env vars.
  `LLM_FAKE=1` returns canned streams for tests/offline dev.
- Identity tables (user/session/account/organization/member) belong to better-auth.
  Engine tables reference better-auth user ids as plain text columns, no FKs.
- Engine API routes live under `/v1/*` and require the BFF-signed service JWT
  (HS256, `ENGINE_SERVICE_SECRET`); `/healthz` is public.
- DB schema changes: new Alembic revision in `apps/engine/src/engine/migrations/versions/`.
- Every PR follows the Definition-of-Done checklist in the PR template.

## Gotchas

- Windows + OneDrive checkout: `.npmrc` pins `node-linker=hoisted` (no junctions) and
  the repo sets `core.longpaths=true`. Don't switch pnpm back to symlink linking.
- `uv` is at `~/.local/bin` — new shells may need `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`.
- Dev Postgres maps to host port **5433** (a local Windows PostgreSQL service owns 5432).
- Engine tests need Postgres running (`pnpm db:up`); they create/drop an `asep_test` db.
