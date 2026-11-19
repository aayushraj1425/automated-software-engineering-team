# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ASEP is an AI Software Engineering Platform. pnpm + Turborepo monorepo: Next.js web app, FastAPI AI engine, shared OpenAPI types. Program plan and phase status live in `docs/ROADMAP.md`; the living backlog is `docs/BACKLOG.md`. Decisions are recorded as ADRs in `docs/architecture/adr/` — read the relevant ADR before changing architecture.

Naming convention: descriptive names only — never shorthand codes. Phases are "Phase 1 — Multi-Agent Engineering Team" (not "M1"); backlog work is referenced by workstream and item name, e.g. "Agent Runtime — Postgres checkpointing per run" (not "Task 1.1.4" or "M1-E1-T4").

## Commands

```sh
pnpm dev / lint / typecheck / test      # turbo fans out to all workspaces
pnpm db:up                              # docker compose dev services
pnpm db:migrate                         # alembic + better-auth migrations
pnpm e2e                                # Playwright smoke (db must be up)
```

Engine-only (run inside `apps/engine`): `uv sync`, `uv run pytest`, `uv run pytest tests/path/test_foo.py::test_name` (single test), `uv run ruff check .`, `uv run ruff format .` (CI enforces formatting — run before every push), `uv run pyright`, `uv run alembic upgrade head`.

Web-only: `pnpm --filter web dev`, `pnpm --filter web test`, `pnpm --filter web auth:migrate`.

## Architecture

### Request flow

Browser → Next.js BFF (`apps/web/src/app/api/`) → Engine (`/v1/*`).

The BFF validates the better-auth session, signs an HS256 service JWT (`ENGINE_SERVICE_SECRET`), and proxies to the engine. Every engine route calls `require_service_auth` to verify that JWT. The BFF never talks to Postgres directly.

### Agent run lifecycle

1. User approves a work item → `POST /v1/runs` → engine creates an `AgentRun` record and spawns a background task (`agents/runner.py`).
2. **Planning phase**: `create_plan` (Product Manager agent) clones the repo into a per-run workspace (`workspace/manager.py`), writes a task board, sets status to `awaiting_approval`.
3. User approves → **Execution phase**: `build_supervisor_graph` (LangGraph, deterministic routing — no LLM) picks the next eligible task by dependency order and dispatches it to the engineer agent (`agents/engineer.py`).
4. Each agent runs the shared loop (`agents/loop.py`): model turn → tool calls → repeat, up to `MAX_TURNS = 24`. Roles and their tool policies live in `agents/registry.py`; prompts are markdown files in `agents/prompts/`.
5. After all tasks: QA sandbox, security scan, PR opened via GitHub/GitLab/Bitbucket.
6. Every status change is an `AgentEvent` row in Postgres. Redis carries a ping on `run-events:<id>` to wake the SSE stream (`events/bus.py`); the stream falls back to a 2 s heartbeat poll if Redis is down.

### LLM routing

All LLM calls go through `engine/llm/router.py` (`ModelRouter`). Never import litellm anywhere else. Three tiers — `planner`, `coder`, `cheap` — map to `MODEL_PLANNER/CODER/CHEAP` env vars. `LLM_FAKE=1` returns canned replies for offline work and tests.

Gemini embedding calls bypass LiteLLM entirely (`_embed_gemini_direct`) because LiteLLM routes `gemini/` embedding models through its Vertex AI handler which targets v1beta — the current default model (`gemini-embedding-001`) is only on v1. Provider API keys for background tasks (e.g. indexing) are read from explicit `Settings` fields (`gemini_api_key`, etc.) — `os.environ` is not populated by pydantic-settings.

### Database / RLS

Two connection pools: `database_url` (owner role) for internal work; `database_url_api` (non-owner `asep_api` role) for user-pinned requests. `db/session.py` wires row-level security: every transaction sets `app.user_id` / `app.org_id` / `app.service` via `set_config`. A session that sets neither sees zero rows. Use `session_scope()` for background tasks; use the `get_session` FastAPI dependency for route handlers.

Embedding columns are `vector(3072)` (gemini-embedding-001). No ANN index exists — pgvector caps HNSW and IVFFlat at 2000 dims. Search uses an exact sequential scan.

### Identity

better-auth owns `user/session/account/organization/member` tables (created by `pnpm --filter web auth:migrate`, not Alembic). Engine tables store better-auth user ids as plain `String(64)` columns with no foreign keys.

## Conventions

- One `.env` at the repo root feeds compose, the engine (pydantic-settings), and the web app (loaded in `next.config.ts`). Never commit `.env`; keep `.env.example` in sync.
- DB schema changes: new Alembic revision in `apps/engine/src/engine/migrations/versions/`.
- `packages/shared` holds generated engine API types — rebuild with `pnpm generate` after changing engine routes.
- Every PR follows the Definition-of-Done checklist in the PR template.
- Keep responses plain and direct. No robotic phrasing, no unnecessary verbosity.

## Gotchas

- Windows + OneDrive: `.npmrc` pins `node-linker=hoisted` and the repo sets `core.longpaths=true`. Don't switch pnpm back to symlinks.
- `uv` is at `~/.local/bin` — new shells may need `$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`.
- Dev Postgres maps to host port **5433**. Local Windows PostgreSQL 18 owns 5432 and PG17 owns 5433 — if PG17 is running it intercepts connections before Docker. Stop it with `Stop-Service postgresql-x64-17` (admin shell) if indexing or sign-up returns auth errors.
- The `asep` DB role must be **NOSUPERUSER** (superusers bypass row-level security). Fresh volumes get this from `infra/docker/postgres-init/`; older volumes need a one-time rebuild: `python -m engine.backup create` → `docker compose down -v` → `up -d` → `python -m engine.backup restore`.
- Engine tests need Postgres running (`pnpm db:up`); they create/drop an `asep_test` db. Pure-logic tests (router, retries) run without Docker — the `prepared_db` fixture is not autouse.
- pydantic-settings does **not** inject `.env` values into `os.environ`. Background tasks that need a provider key (e.g. embedding) must read it from a `Settings` field, not `os.environ.get(...)`.
