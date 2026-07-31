# Troubleshooting

Common problems and the fastest way past them. Most of these are environment
issues on a fresh machine, not bugs.

## Setup and environment

**`pnpm db:up` fails or hangs.**
Docker Desktop isn't running (or, on Windows, its WSL2 backend hasn't finished
starting). Start it, wait for the whale icon to settle, and retry. The first run
also pulls images, which can take a few minutes.

**Postgres connection refused, or the app can't reach the database.**
The dev Postgres is on **host port 5433**, not 5432 — a local Windows Postgres
service commonly owns 5432, so the compose stack deliberately avoids it. Check
your `DATABASE_URL` points at `localhost:5433`.

**`uv: command not found`.**
`uv` installs to `~/.local/bin`, which a fresh shell may not have on `PATH`. On
Windows PowerShell:
```powershell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
```

**pnpm install behaves strangely under OneDrive.**
`.npmrc` pins `node-linker=hoisted` on purpose — the default linker creates
junctions OneDrive can't follow. Don't switch it back to symlink linking.

## Running the app

**Chat returns the same canned reply every time.**
`LLM_FAKE=1` is set (the default in a fresh `.env`). That's the offline mode —
it proves the pipeline works without an API key. Set `LLM_FAKE=0` and add a
provider key for real output.

**Every engine call returns 401.**
The engine only trusts the BFF-signed service JWT. If you're calling `/v1/*`
directly (curl, Postman), you won't have one — go through the web app's `/api/*`
routes instead. If the *web app* is getting 401s from the engine, check that
`ENGINE_SERVICE_SECRET` is identical for both (they share one `.env`, so this
usually means a stale process — restart `pnpm dev`).

**A run is stuck or ended unexpectedly.**
The run's timeline on `/runs/<id>` is its flight recorder — every agent action is
an `agent_events` row. Read it first. In the engine, every failure funnels through
`_fail_run` in `agents/runner.py`, so a breakpoint there catches every way a run
can die.

**Agent runs do nothing / no pull request opens.**
Opening a PR needs `GITHUB_TOKEN` set and the repository to be on a supported host.
Without it, the run still executes and commits inside its clone — it just stops at
"branch pushed" (or "workspace only" for a local repo). This is expected in a
bare-bones dev setup.

**The test sandbox is skipped.**
The Docker sandbox needs Docker running. When it isn't, the run records the skip
and continues (unless `SANDBOX_REQUIRED=1`, which fails the run instead). This is
by design, so a machine without Docker can still exercise the rest of the pipeline.

## Database and tests

**`pnpm test` (engine) errors with connection failures.**
The engine suite needs Postgres up (`pnpm db:up`). It creates and drops its own
`asep_test` database, so you don't need to prepare one — but the server has to be
reachable on 5433.

**Tests fail with a row-level-security or permissions error.**
The suite runs under RLS in two-role mode and needs both `DATABASE_URL` and
`DATABASE_URL_API`. It also requires the `asep` role to be a **non-superuser** —
superusers silently bypass RLS, so a superuser role makes the security tests fail
loudly (which is the point). Fresh compose volumes create the roles correctly via
`infra/docker/postgres-init`; an older volume may need a one-time rebuild (dump →
`docker compose down -v` → up → restore — see the
[disaster-recovery runbook](runbooks/DISASTER_RECOVERY.md)).

**"I can't see my own data" through the API.**
Row-level security pins a session to its JWT subject. If a query returns nothing it
should, check the session is actually pinned (going through the normal request
path sets it) and that `DATABASE_URL_API` is configured. See
[`architecture/security/ROW_LEVEL_SECURITY.md`](architecture/security/ROW_LEVEL_SECURITY.md).

**`alembic upgrade head` reports success but the schema didn't change.**
This exact class of bug bit the project once: a migration that joined an existing
transaction was never committed, so every upgrade rolled back silently. If you're
writing a migration that manages its own transaction, make sure it commits. The
end-to-end smoke test now runs migrations against a real database precisely to
catch this.

**Async errors mentioning the event loop on Windows.**
psycopg's async driver can't run on Windows' default Proactor event loop. The test
suite sets the selector policy in `conftest.py`; if you hit this in your own
script, set `asyncio.WindowsSelectorEventLoopPolicy()` before creating the loop.

## When none of the above fits

- Reproduce it offline with `LLM_FAKE=1` — deterministic and free.
- Read the relevant design note under [`architecture/`](architecture/); the module
  docstring usually names it.
- Read the test for the area (`apps/engine/tests/test_<area>.py`) — it's an
  executable description of the intended behavior.
