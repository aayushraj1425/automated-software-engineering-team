# Development

How to work in this codebase day to day: the commands, the conventions, how to
add a feature, and how testing is set up. If you haven't run the project yet,
start with [Getting started](getting-started.md).

## Commands

Everything fans out through Turborepo from the repo root:

```sh
pnpm dev          # web + engine dev servers
pnpm lint         # ESLint (web) + ruff (engine)
pnpm typecheck    # tsc (web) + pyright (engine)
pnpm test         # Vitest (web) + pytest (engine)
pnpm e2e          # Playwright smoke — needs the DB up, uses LLM_FAKE
pnpm generate     # regenerate packages/shared from the engine's OpenAPI schema
pnpm db:up        # start Postgres, Redis, MinIO
pnpm db:migrate   # Alembic upgrade + better-auth migrate
```

Inside `apps/engine`, work through `uv`:

```sh
uv run pytest                  # the engine suite (needs Postgres up)
uv run ruff check .            # lint
uv run ruff format --check .   # formatting — CI enforces this, so run it before pushing
uv run pyright                 # type check
uv run alembic upgrade head    # apply migrations
```

## Conventions

These are the house rules. Following them keeps the codebase consistent and the
reviews short.

- **One `.env` at the root** feeds compose, the engine, and the web app. Never
  commit it; when you add a variable, document it in `.env.example`.
- **All model calls go through `engine/llm/router.py`.** Never call `litellm`
  elsewhere. This is what makes tiering, budgets, and `LLM_FAKE` work.
- **Identity tables belong to better-auth.** Engine tables reference user ids as
  plain text, never with a foreign key.
- **Every engine route lives under `/v1/*`** and requires the service JWT;
  `/healthz` is the only exception.
- **Schema changes are Alembic migrations** in
  `apps/engine/src/engine/migrations/versions/`. Row-level-security policy is
  defined once in `engine/db/rls.py`; migrations freeze a copy in time.
- **Descriptive names only.** No shorthand codes — phases and work are referred to
  by name ("Agent Runtime — Postgres checkpointing"), never by an opaque
  identifier. This applies to docs and commit messages too.
- **Design note before code.** Every feature gets a short note under
  `docs/architecture/` explaining the intent and the trade-off, written before the
  implementation.

## Adding a feature

The pull-request template is the Definition of Done, and it mirrors the order the
work is best done in:

1. **Design note.** Write a short note under the matching area folder in
   `docs/architecture/` (for example `docs/architecture/agents/YOUR_FEATURE.md`)
   — what it does, why, and what you deliberately left out. See the
   [architecture index](architecture/README.md) for the areas. This is a real
   design step, not paperwork; it's where you catch the wrong approach cheaply.
2. **API and schema.** If the engine's surface changes, update the router and run
   `pnpm generate` so `packages/shared` stays in sync. If the database changes,
   add an Alembic migration.
3. **Implementation.** Keep the change at the right altitude — extend the shared
   mechanism rather than bolting on a special case. The codebase has strong
   examples of this (the host-agnostic publish path, the one BFF proxy helper).
4. **Tests.** Unit tests for logic; an integration test for the wired path.
   `LLM_FAKE=1` keeps agent-related tests deterministic and offline.
5. **Docs.** Update the design note, the `README`/guides if the surface changed,
   and move the item in `docs/BACKLOG.md`.

A good model to imitate: pick a recent, self-contained feature from
[`docs/BACKLOG.md`](BACKLOG.md)'s Done section, open its design note and its
commit, and follow how the note, the code, and the tests line up.

## Testing

The engine suite needs Postgres running (`pnpm db:up`). It creates and drops its
own `asep_test` database, and — importantly — it runs the **entire suite under
row-level security in two-role mode**, so every ownership-scoped test also proves
the security policies hold. That's why the tests want both `DATABASE_URL` and
`DATABASE_URL_API`, and why the `asep` role must be a non-superuser (a superuser
silently bypasses RLS).

Patterns worth knowing:

- **`LLM_FAKE=1`** returns canned model streams, so agent runs are deterministic.
  Reproduce most bugs offline in seconds instead of spending tokens.
- **Pure builders over the database.** A lot of logic is written as pure functions
  over the domain objects (`build_run_report`, `build_pull_request_body`,
  `build_audit_log`), so it's unit-testable with no database at all.
- **The route-auth sweep.** A test calls every engine route unauthenticated and
  fails if any of them doesn't return 401 — so per-route auth is a structural
  guarantee, not a convention someone has to remember.

Run a single file while iterating:

```sh
cd apps/engine && uv run pytest tests/test_runs_api.py -q
```

## Regenerating shared types

`packages/shared` is generated from the engine's OpenAPI schema — never edit it by
hand. After changing an engine response model, run `pnpm generate` and commit the
result alongside the change.

## Windows and OneDrive notes

This repo is often developed on Windows under OneDrive, which has two sharp edges
the setup already handles — don't undo them:

- `.npmrc` pins `node-linker=hoisted` so pnpm doesn't create junctions OneDrive
  can't follow. Leave it hoisted.
- `core.longpaths=true` is set for the same reason.
- `uv` lives at `~/.local/bin`; a fresh shell may need it on `PATH`
  (`$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"`).

More sharp edges — the 5433 port, the non-superuser role, event-loop policy — are
in [Troubleshooting](troubleshooting.md).
