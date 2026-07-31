# Getting started

This guide takes you from a fresh clone to a running system you can watch work.
It should take about fifteen minutes, most of which is Docker pulling images and
`uv` building the Python environment.

If you want to understand *what* the system does before setting it up, read
[How it works](HOW_IT_WORKS.md) first.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node | 22+ | The web app and tooling |
| pnpm | 11+ | Workspace package manager (`corepack enable` installs it) |
| Python | 3.12+ | The engine |
| uv | latest | Python environment and runner — [install guide](https://docs.astral.sh/uv/) |
| Docker Desktop | latest | Runs Postgres, Redis, and MinIO locally (WSL2 backend on Windows) |

You do **not** need an AI provider key to get started. `LLM_FAKE=1` (the default
in a fresh `.env`) returns canned model responses, so the whole app — including
agent runs — works offline. Add a real key later when you want real output.

## Setup

```sh
# 1. Configuration — one .env at the repo root drives everything
cp .env.example .env

# 2. Dependencies
pnpm install
cd apps/engine && uv sync && cd ../..

# 3. Start the data stores (Postgres on 5433, Redis, MinIO)
pnpm db:up

# 4. Create the database schema (engine tables + auth tables)
pnpm db:migrate

# 5. Run the web app and engine together
pnpm dev
```

`pnpm dev` starts the web app on http://localhost:3000 and the engine on
http://localhost:8000. Sign up at http://localhost:3000/sign-up (email and
password work out of the box; OAuth buttons appear only if you set provider
credentials), then open `/chat` and send a message.

### Did it work?

- **Chat** streams a reply token by token. With `LLM_FAKE=1` the reply is a fixed
  canned message — that is expected, and it confirms the whole path (browser →
  BFF → engine → model → back) is wired correctly.
- **Reload the page.** Your conversation is still there, which proves it persisted
  to Postgres.
- Visit http://localhost:8000/healthz — it should return `{"status":"ok"}`. This
  is the only engine route that does not require authentication.

To see the agent team, open `/repositories`, connect a repository (a local path
or a public URL both work in dev), then open `/runs` and describe a small feature.
In `LLM_FAKE` mode the run uses a fixed plan but does real work — real files, real
git commits, a real timeline — so it is a safe way to learn the pipeline without
spending tokens.

## Configuration

Everything is configured through the root `.env`. [`.env.example`](../.env.example)
documents every variable inline; this section explains the choices that aren't
obvious.

### Models and providers

Set at least one provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or
`GEMINI_API_KEY`) and flip `LLM_FAKE=0` for real output. The engine routes work to
three tiers so you can trade cost against quality:

- `MODEL_PLANNER` — the expensive, careful model for planning and review.
- `MODEL_CODER` — the day-to-day model for writing code.
- `MODEL_CHEAP` — a small model for cheap, high-volume calls.

Any [LiteLLM-supported model id](https://docs.litellm.ai/docs/providers) works.
`MODEL_EMBEDDING` powers repository indexing and must produce 768-dimensional
vectors.

### Data stores

The compose defaults in `.env.example` match the services `pnpm db:up` starts, so
they work unchanged. Two things to know:

- **Postgres is on host port 5433**, not the usual 5432. A local Windows Postgres
  service commonly owns 5432, so the compose stack sidesteps it.
- **`DATABASE_URL_API`** is a second, non-owner database role (`asep_api`). User
  requests connect through it so that even raw SQL on a user session cannot bypass
  row-level security. Leaving it empty falls back to single-role mode, which is
  fine for a quick look but not how the tests or production run. See
  [Row-Level Security](architecture/security/ROW_LEVEL_SECURITY.md).

### Secrets at rest

`ENGINE_ENCRYPTION_KEY` (base64, 32 bytes) encrypts things like bring-your-own
provider keys and integration tokens. If you leave it empty, the engine derives a
development key from `ENGINE_SERVICE_SECRET` and warns loudly at startup — fine
for dev, but set a dedicated value in production.

### Optional subsystems

Several features are off by default and gated behind a single variable each:
`SANDBOX_ENABLED` (Docker test sandbox), `GITHUB_TOKEN` and
`GITHUB_WEBHOOK_SECRET` (pull requests and the webhook reviewer), `RATE_LIMIT_*`,
`BACKUP_*`, and `OTEL_*`. Each is documented inline in `.env.example` with a
pointer to its design note.

## Running the pieces separately

`pnpm dev` is the easy path, but you can run each side on its own:

```sh
# Engine only (from apps/engine)
uv run uvicorn engine.serve:app --reload --port 8000

# Web only (from apps/web)
pnpm dev

# Agent runs on a queue instead of inline (needs a worker)
# set RUN_QUEUE=arq in .env, then:
cd apps/engine && uv run arq engine.worker.WorkerSettings
```

By default runs execute inline (a background task inside the API process), which
is simplest for local work. Set `RUN_QUEUE=arq` to move them onto a Redis queue
processed by a separate worker — closer to production, and how graceful-restart
recovery is exercised. See [Background Worker](architecture/agents/BACKGROUND_WORKER.md).

## Next steps

- [Development](development.md) — how to work in the codebase and add a feature.
- [Architecture](architecture.md) — how the system is shaped and why.
- [Troubleshooting](troubleshooting.md) — if any step above misbehaved.
